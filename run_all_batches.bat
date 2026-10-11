@echo off
rem ===========================================================================
rem  Crawl ALL 6 university batches back-to-back (universities 001-272).
rem  Just leave it running. Each batch pauses for 15 min between passes and
rem  only moves to the next batch when the current one is fully scraped.
rem  Everything lands in uk_university/ (one file per university + index.json).
rem
rem  Progress:  tail -f crawl_run.log       or       python scrape.py --stats --input urls.txt
rem  Stop:      close this window / reboot - nothing is lost, just run it again.
rem ===========================================================================
setlocal
cd /d "%~dp0"

for %%N in (1 2 3 4 5 6) do (
  echo [%date% %time%] === starting batch %%N of 6 ===
  call run_batch.bat %%N
  if errorlevel 1 (
    echo [%date% %time%] batch %%N failed - stopping. Fix and re-run run_all_batches.bat
    exit /b 1
  )
  echo [%date% %time%] batch %%N done
)

echo [%date% %time%] === ALL 6 BATCHES COMPLETE: all 272 UK universities scraped ===
exit /b 0
