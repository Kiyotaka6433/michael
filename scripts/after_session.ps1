# Slow work queued after an interactive session (writer-model heavy), in order, below normal priority:
#   1. recall experiment: quote-anchored repair, measured on the 14 baseline notes (eval/gate_repair.py, GATE_TAG=quote)
#   2. recall experiment: extractive drafting of the 14 baseline notes (eval/extractive_drafts.py; resumable)
#   3. the library batch: topic rewrites (compare-and-replace), then key points (unused articles first)
# Each step is resumable; output goes through cmd so logs stay UTF-8.
$root = "C:\Users\aryan\OneDrive\Desktop\michael"
Set-Location $root
$py = "$root\.venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
Start-Process -WindowStyle Hidden powershell -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File","$root\scripts\keep_responsive.ps1"
cmd /c "set MICHAEL_QUOTE_REPAIR=1&& set GATE_TAG=quote&& `"$py`" -u eval\gate_repair.py >> eval\reports\after_session.log 2>&1"
cmd /c "set MICHAEL_WRITER_STYLE=extractive&& `"$py`" -u eval\extractive_drafts.py >> eval\reports\after_session.log 2>&1"
& "$root\scripts\after_batch.ps1"
