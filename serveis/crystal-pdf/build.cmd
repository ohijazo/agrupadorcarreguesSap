@echo off
rem Compila crystal-pdf.exe amb el csc de .NET Framework (no cal Visual Studio).
rem Cal el runtime "SAP Crystal Reports for .NET Framework" 64 bits instalat:
rem es compila contra les DLL 13.0.4000.0 del GAC, que comparteixen tots els SP.
setlocal
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
set GAC=%WINDIR%\Microsoft.NET\assembly\GAC_MSIL
set ENG=%GAC%\CrystalDecisions.CrystalReports.Engine\v4.0_13.0.4000.0__692fbea5521e1304\CrystalDecisions.CrystalReports.Engine.dll
set SHA=%GAC%\CrystalDecisions.Shared\v4.0_13.0.4000.0__692fbea5521e1304\CrystalDecisions.Shared.dll
if not exist "%ENG%" (echo No trobo el runtime de Crystal 13.0.4000.0 & exit /b 1)
if not exist "%~dp0bin" mkdir "%~dp0bin"
"%CSC%" -nologo -optimize+ -platform:x64 -target:exe -out:"%~dp0bin\crystal-pdf.exe" ^
  -r:System.Configuration.dll -r:System.ServiceProcess.dll -r:System.Data.dll ^
  -r:"%ENG%" -r:"%SHA%" "%~dp0CrystalPdf.cs" || exit /b 1
if not exist "%~dp0bin\crystal-pdf.exe.config" copy "%~dp0crystal-pdf.exe.config.example" "%~dp0bin\crystal-pdf.exe.config" >nul
echo Compilat: %~dp0bin\crystal-pdf.exe
