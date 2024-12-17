# Create a service that maintains an RDP session
$ServiceName = "PersistentRDP"
$ServicePath = "C:\Windows\System32\mstsc.exe"
$Arguments = "/v:localhost /admin /noconsentprompt"

# Create service
$service = New-Service -Name $ServiceName `
    -DisplayName "Persistent RDP Session" `
    -Description "Maintains a persistent RDP session for automation" `
    -BinaryPathName "$ServicePath $Arguments" `
    -StartupType Automatic

# Set service to restart on failure
sc.exe failure $ServiceName reset= 86400 actions= restart/5000