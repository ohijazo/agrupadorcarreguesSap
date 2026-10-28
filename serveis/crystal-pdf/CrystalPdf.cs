// Servei de PDF amb els Crystal de SAP Business One.
//
// L'app Flask viu a Ubuntu i Crystal nomes funciona a Windows. Aquest servei
// corre al servidor de SAP, que ja te el runtime de Crystal per a .NET i el
// driver OLE DB amb que estan desats els reports. L'app li demana
// `GET /pdf?tipus=DLN2&docentry=148` i ell:
//
//   1. llegeix de SAP el layout per defecte del tipus (RTYP.DEFLT_REP) i el
//      .rpt sencer (RDOC.Template). Es llegeix a CADA peticio: si algu canvia
//      el layout a SAP, el PDF canvia sense tocar res aqui;
//   2. reapunta totes les taules (i subinformes) a la BD configurada;
//   3. hi posa `DocKey@` = docentry, que es exactament el que fa SAP;
//   4. retorna el PDF.
//
// Tambe s'executa a ma per provar: `crystal-pdf.exe --prova DLN2 148 a.pdf`.
// Vegeu README.md.
using System;
using System.Collections.Generic;
using System.Configuration;
using System.Data.SqlClient;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.ServiceProcess;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using CrystalDecisions.CrystalReports.Engine;
using CrystalDecisions.Shared;

namespace CrystalPdf
{
    // Tipus de document que es poden demanar, i la taula de capcalera on es
    // comprova que el document existeix. Sense aquesta comprovacio, un
    // docentry inexistent dona un PDF en blanc en lloc d'un 404.
    static class Tipus
    {
        public static readonly Dictionary<string, string> Capcalera = new Dictionary<string, string>
        {
            { "DLN2", "ODLN" },   // Albara de venda (articles)
        };
    }

    class Config
    {
        public int Port;
        public string Escolta;     // + = totes les interficies; localhost per provar sense admin
        public string Token;
        public string SqlServer, SqlDatabase, SqlUser, SqlPassword;
        // SqlUser buit = seguretat integrada: el servei entra a SQL amb el seu
        // compte de Windows (NT SERVICE\CrystalPdf) i no hi ha cap contrasenya
        // enlloc. Es la configuracio de produccio.
        public bool Integrada { get { return SqlUser == ""; } }
        public string Proveidor;     // buit = el que porta el .rpt (MSOLEDBSQL)
        public int MaxJobs;
        public int EsperaJobSegons;
        public string DirTreball;

        public static Config Llegeix()
        {
            var a = ConfigurationManager.AppSettings;
            var dir = AppDomain.CurrentDomain.BaseDirectory;
            var c = new Config
            {
                Port = int.Parse(a["Port"] ?? "8095"),
                Escolta = a["Escolta"] ?? "+",
                Token = a["Token"] ?? "",
                SqlServer = a["SqlServer"] ?? "localhost",
                SqlDatabase = a["SqlDatabase"] ?? "",
                SqlUser = a["SqlUser"] ?? "",
                SqlPassword = a["SqlPassword"] ?? "",
                Proveidor = a["Proveidor"] ?? "",
                MaxJobs = int.Parse(a["MaxJobs"] ?? "2"),
                EsperaJobSegons = int.Parse(a["EsperaJobSegons"] ?? "30"),
                DirTreball = Path.Combine(dir, "treball"),
            };
            if (c.Token.Length < 24)
                throw new ConfigurationErrorsException("Token ha de tenir com a minim 24 caracters");
            if (c.SqlDatabase == "")
                throw new ConfigurationErrorsException("Falta SqlDatabase");
            Directory.CreateDirectory(c.DirTreball);
            return c;
        }

        public string CadenaSql()
        {
            var b = new SqlConnectionStringBuilder
            {
                DataSource = SqlServer, InitialCatalog = SqlDatabase,
                ApplicationName = "CrystalPdf", ConnectTimeout = 10,
            };
            if (Integrada) b.IntegratedSecurity = true;
            else { b.UserID = SqlUser; b.Password = SqlPassword; }
            return b.ConnectionString;
        }
    }

    class DocumentNoTrobat : Exception
    {
        public DocumentNoTrobat(string m) : base(m) { }
    }

    static class Log
    {
        static readonly object Pany = new object();
        public static void Escriu(string text)
        {
            var linia = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " " + text;
            lock (Pany)
            {
                try
                {
                    var dir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "logs");
                    Directory.CreateDirectory(dir);
                    File.AppendAllText(Path.Combine(dir, DateTime.Now.ToString("yyyy-MM") + ".log"),
                                       linia + Environment.NewLine, Encoding.UTF8);
                }
                catch { /* sense log abans que sense servei */ }
                if (Environment.UserInteractive) Console.WriteLine(linia);
            }
        }
    }

    class Generador
    {
        readonly Config cfg;
        readonly SemaphoreSlim jobs;

        public Generador(Config cfg)
        {
            this.cfg = cfg;
            jobs = new SemaphoreSlim(cfg.MaxJobs);
        }

        // Retorna el cami del .rpt per defecte del tipus. El fitxer es desa amb
        // el hash del contingut: si el layout canvia a SAP surt un fitxer nou,
        // i mai no es carrega un .rpt a mig escriure.
        string Layout(SqlConnection cn, string tipus)
        {
            using (var cmd = new SqlCommand(
                "SELECT d.DocCode, d.Template FROM RTYP t JOIN RDOC d ON d.DocCode = t.DEFLT_REP " +
                "WHERE t.CODE = @t", cn))
            {
                cmd.Parameters.AddWithValue("@t", tipus);
                using (var r = cmd.ExecuteReader())
                {
                    if (!r.Read()) throw new InvalidOperationException("No hi ha layout per defecte per a " + tipus);
                    var codi = r.GetString(0);
                    if (r.IsDBNull(1)) throw new InvalidOperationException(codi + " no es un Crystal (es un layout del sistema)");
                    var bytes = (byte[])r[1];
                    string hash;
                    using (var sha = SHA256.Create())
                        hash = BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").Substring(0, 16);
                    var cami = Path.Combine(cfg.DirTreball, codi + "_" + hash + ".rpt");
                    if (!File.Exists(cami))
                    {
                        var tmp = cami + "." + Guid.NewGuid().ToString("N") + ".tmp";
                        File.WriteAllBytes(tmp, bytes);
                        try { File.Move(tmp, cami); }
                        catch (IOException) { File.Delete(tmp); }   // un altre fil ja l'ha deixat
                        EsborraVersionsAntigues(codi, cami);
                    }
                    return cami;
                }
            }
        }

        // Nomes es guarda la versio vigent de cada layout (~300 KB). Si una
        // versio vella encara s'esta fent servir, es deixa per a la propera.
        void EsborraVersionsAntigues(string codi, string vigent)
        {
            foreach (var f in Directory.GetFiles(cfg.DirTreball, codi + "_*"))
            {
                if (string.Equals(f, vigent, StringComparison.OrdinalIgnoreCase)) continue;
                try { File.Delete(f); } catch (IOException) { } catch (UnauthorizedAccessException) { }
            }
        }

        static int? NumDocument(SqlConnection cn, string taula, int docEntry)
        {
            // `taula` surt del diccionari Tipus, mai de la peticio.
            using (var cmd = new SqlCommand("SELECT DocNum FROM " + taula + " WHERE DocEntry = @d", cn))
            {
                cmd.Parameters.AddWithValue("@d", docEntry);
                var v = cmd.ExecuteScalar();
                return v == null || v is DBNull ? (int?)null : Convert.ToInt32(v);
            }
        }

        void Reapunta(ReportDocument r)
        {
            foreach (Table t in r.Database.Tables)
            {
                var li = t.LogOnInfo;
                var ci = li.ConnectionInfo;
                ci.ServerName = cfg.SqlServer;
                ci.DatabaseName = cfg.SqlDatabase;
                if (cfg.Integrada) ci.IntegratedSecurity = true;
                else { ci.UserID = cfg.SqlUser; ci.Password = cfg.SqlPassword; }
                foreach (NameValuePair2 a in ci.Attributes.Collection)
                {
                    if (a.Name.ToString() != "QE_LogonProperties") continue;
                    foreach (NameValuePair2 p in ((DbConnectionAttributes)a.Value).Collection)
                    {
                        var nom = p.Name.ToString();
                        if (nom == "Data Source") p.Value = cfg.SqlServer;
                        else if (nom == "Initial Catalog") p.Value = cfg.SqlDatabase;
                        else if (nom == "Provider" && cfg.Proveidor != "") p.Value = cfg.Proveidor;
                        else if (nom == "Integrated Security") p.Value = cfg.Integrada;
                    }
                }
                t.ApplyLogOnInfo(li);
            }
        }

        public byte[] Pdf(string tipus, int docEntry, out int docNum)
        {
            string taula;
            if (!Tipus.Capcalera.TryGetValue(tipus, out taula))
                throw new ArgumentException("Tipus no permes: " + tipus);

            string rpt;
            using (var cn = new SqlConnection(cfg.CadenaSql()))
            {
                cn.Open();
                var num = NumDocument(cn, taula, docEntry);
                if (num == null) throw new DocumentNoTrobat(tipus + " " + docEntry + " no existeix");
                docNum = num.Value;
                rpt = Layout(cn, tipus);
            }

            // Crystal te un limit de jobs simultanis per proces i cada export
            // carrega CPU: millor fer cua curta que tombar el servidor de SAP.
            if (!jobs.Wait(TimeSpan.FromSeconds(cfg.EsperaJobSegons)))
                throw new System.TimeoutException("Massa PDF alhora; torna-ho a provar");
            try
            {
                var r = new ReportDocument();
                try
                {
                    r.Load(rpt);
                    Reapunta(r);
                    foreach (ReportDocument s in r.Subreports) Reapunta(s);
                    r.SetParameterValue("DocKey@", docEntry);
                    using (var st = r.ExportToStream(ExportFormatType.PortableDocFormat))
                    using (var ms = new MemoryStream())
                    {
                        st.CopyTo(ms);
                        return ms.ToArray();
                    }
                }
                finally
                {
                    // Sense Close+Dispose, Crystal esgota el limit de jobs
                    // (75 per defecte) i deixa de generar fins que es reinicia.
                    r.Close();
                    r.Dispose();
                }
            }
            finally { jobs.Release(); }
        }
    }

    class Servidor
    {
        readonly Config cfg;
        readonly Generador gen;
        readonly HttpListener http = new HttpListener();

        public Servidor(Config cfg)
        {
            this.cfg = cfg;
            gen = new Generador(cfg);
            http.Prefixes.Add("http://" + cfg.Escolta + ":" + cfg.Port + "/");
        }

        public void Arrenca()
        {
            http.Start();
            Log.Escriu("Escoltant al port " + cfg.Port + " (BD " + cfg.SqlDatabase + ")");
            Task.Run(() => Bucle());
        }

        public void Atura()
        {
            try { http.Stop(); http.Close(); } catch { }
            Log.Escriu("Aturat");
        }

        async Task Bucle()
        {
            while (http.IsListening)
            {
                HttpListenerContext ctx;
                try { ctx = await http.GetContextAsync(); }
                catch (Exception) { if (!http.IsListening) return; continue; }
                var _ = Task.Run(() => Atén(ctx));
            }
        }

        static bool TokenOk(string rebut, string esperat)
        {
            // Comparacio en temps constant.
            if (rebut == null) return false;
            var a = Encoding.UTF8.GetBytes(rebut);
            var b = Encoding.UTF8.GetBytes(esperat);
            var dif = a.Length ^ b.Length;
            for (var i = 0; i < Math.Min(a.Length, b.Length); i++) dif |= a[i] ^ b[i];
            return dif == 0;
        }

        static void Respon(HttpListenerResponse resp, int codi, string text)
        {
            var b = Encoding.UTF8.GetBytes(text);
            resp.StatusCode = codi;
            resp.ContentType = "text/plain; charset=utf-8";
            resp.ContentLength64 = b.Length;
            resp.OutputStream.Write(b, 0, b.Length);
        }

        void Atén(HttpListenerContext ctx)
        {
            var req = ctx.Request;
            var resp = ctx.Response;
            var t0 = DateTime.Now;
            try
            {
                var cami = req.Url.AbsolutePath.TrimEnd('/');
                if (req.HttpMethod != "GET") { Respon(resp, 405, "Nomes GET"); return; }
                if (cami == "/health") { Respon(resp, 200, "ok"); return; }
                if (cami != "/pdf") { Respon(resp, 404, "No existeix"); return; }
                if (!TokenOk(req.Headers["X-Token"], cfg.Token)) { Respon(resp, 401, "Token incorrecte"); return; }

                var tipus = (req.QueryString["tipus"] ?? "").ToUpperInvariant();
                int docEntry;
                if (!int.TryParse(req.QueryString["docentry"], out docEntry) || docEntry <= 0)
                {
                    Respon(resp, 400, "docentry ha de ser un enter positiu");
                    return;
                }

                int docNum;
                var pdf = gen.Pdf(tipus, docEntry, out docNum);
                resp.StatusCode = 200;
                resp.ContentType = "application/pdf";
                resp.AddHeader("X-DocNum", docNum.ToString());
                resp.ContentLength64 = pdf.Length;
                resp.OutputStream.Write(pdf, 0, pdf.Length);
                Log.Escriu(string.Format("OK {0} {1} (num {2}) {3} bytes en {4:0} ms des de {5}",
                    tipus, docEntry, docNum, pdf.Length, (DateTime.Now - t0).TotalMilliseconds, req.RemoteEndPoint));
            }
            catch (ArgumentException e) { Respon(resp, 400, e.Message); }
            catch (DocumentNoTrobat e) { Respon(resp, 404, e.Message); }
            catch (System.TimeoutException e) { Respon(resp, 503, e.Message); }
            catch (Exception e)
            {
                Log.Escriu("ERROR " + req.Url.PathAndQuery + ": " + e);
                try { Respon(resp, 500, "Error generant el PDF: " + e.GetBaseException().Message); } catch { }
            }
            finally
            {
                try { resp.Close(); } catch { }
            }
        }
    }

    class ServeiWindows : ServiceBase
    {
        Servidor srv;
        public ServeiWindows() { ServiceName = "CrystalPdf"; }
        protected override void OnStart(string[] args)
        {
            srv = new Servidor(Config.Llegeix());
            srv.Arrenca();
        }
        protected override void OnStop() { if (srv != null) srv.Atura(); }
    }

    static class Programa
    {
        static int Main(string[] args)
        {
            if (!Environment.UserInteractive)
            {
                ServiceBase.Run(new ServeiWindows());
                return 0;
            }
            try
            {
                if (args.Length == 1 && args[0] == "--protegeix")
                {
                    // Xifra <appSettings> amb DPAPI de la maquina: el fitxer
                    // nomes es pot llegir en aquest servidor. El servei el
                    // desxifra sol; per editar-lo, --desprotegeix.
                    var conf = ConfigurationManager.OpenExeConfiguration(ConfigurationUserLevel.None);
                    var sec = conf.GetSection("appSettings");
                    if (!sec.SectionInformation.IsProtected)
                        sec.SectionInformation.ProtectSection("DataProtectionConfigurationProvider");
                    conf.Save();
                    Console.WriteLine("appSettings xifrat a " + conf.FilePath);
                    return 0;
                }
                if (args.Length == 1 && args[0] == "--desprotegeix")
                {
                    var conf = ConfigurationManager.OpenExeConfiguration(ConfigurationUserLevel.None);
                    conf.GetSection("appSettings").SectionInformation.UnprotectSection();
                    conf.Save();
                    Console.WriteLine("appSettings desxifrat a " + conf.FilePath + ": torna a fer --protegeix quan acabis");
                    return 0;
                }
                var cfg = Config.Llegeix();
                if (args.Length == 4 && args[0] == "--prova")
                {
                    // crystal-pdf.exe --prova DLN2 148 sortida.pdf
                    var t0 = DateTime.Now;
                    int docNum;
                    var pdf = new Generador(cfg).Pdf(args[1].ToUpperInvariant(), int.Parse(args[2]), out docNum);
                    File.WriteAllBytes(args[3], pdf);
                    Console.WriteLine("OK: document " + docNum + ", " + pdf.Length + " bytes en "
                                      + (DateTime.Now - t0).TotalMilliseconds.ToString("0") + " ms -> " + args[3]);
                    return 0;
                }
                // Sense arguments: servidor en primer pla (per provar-lo abans d'instal·lar-lo).
                var srv = new Servidor(cfg);
                srv.Arrenca();
                Console.WriteLine("Prem Enter per aturar.");
                Console.ReadLine();
                srv.Atura();
                return 0;
            }
            catch (Exception e)
            {
                Console.Error.WriteLine("ERROR: " + e.GetBaseException().Message);
                Log.Escriu("ERROR arrencant: " + e);
                return 1;
            }
        }
    }
}
