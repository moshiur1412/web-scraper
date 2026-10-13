@echo off
rem ===========================================================================
rem  Create NEW batch file(s) from a text file of URLs, then print the command
rem  to run them. Existing batches are never touched or deleted.
rem
rem  Usage:   create_batch.bat my_urls.txt            (50 URLs per batch file)
rem           create_batch.bat my_urls.txt 25         (25 URLs per batch file)
rem
rem  my_urls.txt = one URL per line, '#' = comment line, blank lines ignored.
rem  Put the file in this folder (or pass a full path).
rem  New files start at the next free number: batch_07.txt, batch_08.txt, ...
rem ===========================================================================
setlocal
set "LIST=%~f1"
set "SIZE=%~2"
cd /d "%~dp0"

if "%~1"=="" (
  echo Usage: create_batch.bat ^<url-list-file^> [batch-size]
  echo.
  echo   1. Make a text file with one URL per line, e.g. my_urls.txt
  echo   2. Run:    create_batch.bat my_urls.txt
  echo   3. Run the new batch with the number printed below, e.g.  run_batch.bat 7
  exit /b 2
)
if not exist "%LIST%" (
  echo [ERROR] file not found: %LIST%
  echo         Put the URL list in this folder, or pass its full path.
  exit /b 2
)

if not exist ".venv\Scripts\activate.bat" (
  echo [ERROR] no .venv found - do the setup first, see README section 2:
  echo         python -m venv .venv   then   .venv\Scripts\activate   then   pip install -r requirements.txt
  exit /b 2
)
call .venv\Scripts\activate.bat

echo Building batch file(s) from %LIST% ...
if "%SIZE%"=="" (
  python make_batches.py --input "%LIST%"
) else (
  python make_batches.py --input "%LIST%" --batch-size %SIZE%
)
if errorlevel 1 goto failed
echo.
echo Done. Now crawl it with:  run_batch.bat ^<number shown above^>
exit /b 0

:failed
echo.
echo [ERROR] batch file not created - see the message above.
exit /b 1
