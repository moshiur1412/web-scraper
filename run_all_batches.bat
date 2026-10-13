@echo off
rem ===========================================================================
rem  Crawl ALL batch files back-to-back (batches\batch_01.txt, batch_02.txt, ...).
rem  Finds every batch file automatically, so it works with the original 6 UK
rem  batches AND with any new batch you create later (create_batch.bat).
rem
rem  Just leave it running. Each batch pauses 15 min between passes and only
rem  moves on when the current one is fully scraped. Everything lands in
rem  uk_university/ (one file per university + index.json).
rem
rem  Progress:  status.bat   or   Get-Content crawl_run.log -Tail 50
rem  Stop:      close this window / reboot - nothing is lost, run it again.
rem ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set TOTAL=0
for %%F in ("batches\batch_*.txt") do if exist "%%~fF" set /a TOTAL+=1
if "%TOTAL%"=="0" goto nobatches
echo Found %TOTAL% batch file(s) in batches\

set DONE=0
for /f "delims=" %%F in ('dir /b /o:n batches\batch_*.txt 2^>nul') do (
  set "NAME=%%~nF"
  set "NUM=!NAME:batch_=!"
  if "!NUM:~0,1!"=="0" set "NUM=!NUM:~1!"
  set /a DONE+=1
  echo [!date! !time!] === batch !NUM! ^(!DONE! of %TOTAL%^) ===
  call run_batch.bat !NUM!
  if errorlevel 1 goto failed
  echo [!date! !time!] batch !NUM! done
)

echo [%date% %time%] === ALL %TOTAL% BATCHES COMPLETE - every seed URL scraped ===
exit /b 0

:nobatches
echo [ERROR] no batches\batch_*.txt files found.
echo         Build them first:  python make_batches.py              - original UK list
echo                            create_batch.bat my_urls.txt        - your own URL list
exit /b 2

:failed
echo [!date! !time!] batch !NUM! failed - stopping. Fix it, then run run_all_batches.bat again - it resumes.
exit /b 1
