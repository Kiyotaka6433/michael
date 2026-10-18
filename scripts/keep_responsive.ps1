# Keeps the laptop responsive while long batch work runs: every 30 s, the writer model's server (llama-server,
# which Ollama starts at AboveNormal priority on every model load) and the library builder are set to BelowNormal.
# Chrome, Obsidian, the extension's backend and anything you click then always get the CPU first; the batch uses
# what's left. Stops by itself when no build_library.py run is left.
$idle = 0
while ($idle -lt 3) {
  $batch = Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -like '*build_library*' }
  if ($batch) { $idle = 0 } else { $idle++ }
  foreach ($p in @(Get-Process llama-server -ErrorAction SilentlyContinue) + @($batch | ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue })) {
    try { if ($p.PriorityClass -ne 'BelowNormal' -and $p.PriorityClass -ne 'Idle') { $p.PriorityClass = 'BelowNormal' } } catch {}
  }
  Start-Sleep 30
}
