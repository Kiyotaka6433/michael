# Waits until no build_library.py run has been active for two checks in a row (the batch chains topics -> keypoints,
# so a single empty check can fall between them), then rewrites the two new topic notes.
$root = "C:\Users\aryan\OneDrive\Desktop\michael"
$idle = 0
while ($idle -lt 2) {
    Start-Sleep 60
    $busy = Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -like '*build_library*' }
    if ($busy) { $idle = 0 } else { $idle++ }
}
Set-Location $root
& "$root\.venv\Scripts\python.exe" scripts/redo_topics.py "DSA and Competitive Programming/Geometry" "DSA and Competitive Programming/Combinatorics and games" *>> library\build.log
& "$root\.venv\Scripts\python.exe" -u scripts/build_library.py topics *>> library\build.log
