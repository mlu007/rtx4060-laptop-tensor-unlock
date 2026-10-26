param(
    [string]$Record = (Join-Path $env:ProgramData 'Gpu4090Unlock\install.json'),
    [switch]$Keep
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Record)) { throw "no install record at $Record" }
$r = Get-Content $Record -Raw | ConvertFrom-Json
$p = Get-Partition | Where-Object { $_.Guid -eq $r.partitionGuid } | Select-Object -First 1
if (-not $p) { throw "partition $($r.partitionGuid) from the install record was not found" }

$added = $false
if (-not $p.DriveLetter) {
    Add-PartitionAccessPath -DiskNumber $p.DiskNumber -PartitionNumber $p.PartitionNumber -AssignDriveLetter
    $p = Get-Partition -DiskNumber $p.DiskNumber -PartitionNumber $p.PartitionNumber
    $added = $true
}
$letter = $p.DriveLetter
$volume = Get-Volume -DriveLetter $letter
Write-Host "volume ${letter}: '$($volume.FileSystemLabel)' $($volume.FileSystem) $([math]::Floor($volume.Size / 1MB)) MB, $([math]::Floor($volume.SizeRemaining / 1MB)) MB free"
Get-ChildItem "${letter}:\" -Recurse -File | ForEach-Object { "{0,12}  {1}" -f $_.Length, $_.FullName }

$logDir = "${letter}:\GPU4090-UNLOCK"
if (Test-Path $logDir) {
    $latest = Get-ChildItem $logDir -Filter 'RUN*.TXT' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latest) {
        Write-Host "`nlatest log: $($latest.Name) ($($latest.Length) bytes, $($latest.LastWriteTime))"
        Get-Content $latest.FullName -Tail 15
    } else {
        Write-Host 'no RUN log in the folder yet'
    }
} else {
    Write-Host 'no GPU4090-UNLOCK folder yet (the app has not run from this volume)'
}

if ($added -and -not $Keep) {
    Remove-PartitionAccessPath -DiskNumber $p.DiskNumber -PartitionNumber $p.PartitionNumber -AccessPath "${letter}:\"
    Write-Host "`ndrive letter ${letter}: removed again"
}