# Evening batch (build_library.py merges its state saves, so fetching sources in parallel is safe):
#   1. rewrite the two new topic notes with the improved retrieval
#   2. rewrite every topic note whose topic gained sources; replace only if better (old one -> <Subject>/Archive/)
#   3. the remaining key-points notes
# Output goes through cmd so library\build.log stays UTF-8 (PowerShell 5.1 redirection writes UTF-16).
$root = "C:\Users\aryan\OneDrive\Desktop\michael"
Set-Location $root
$py = "$root\.venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
cmd /c "`"$py`" scripts/redo_topics.py `"DSA and Competitive Programming/Geometry`" `"DSA and Competitive Programming/Combinatorics and games`" >> library\build.log 2>&1"
cmd /c "`"$py`" -u scripts/build_library.py topics >> library\build.log 2>&1"
cmd /c "`"$py`" -u scripts/build_library.py retopics >> library\build.log 2>&1"
cmd /c "`"$py`" -u scripts/build_library.py keypoints >> library\build.log 2>&1"
