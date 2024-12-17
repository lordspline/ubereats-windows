# Replace these with your actual credentials
$Username = "Administrator"
$Password = "Jzl%Jde$bLiEi%-%I=$IxIn=Rga5LrN8"
$Domain = $env:COMPUTERNAME

# Registry path for autologon
$RegPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"

# Set registry values for autologon
Set-ItemProperty -Path $RegPath -Name "AutoAdminLogon" -Value "1"
Set-ItemProperty -Path $RegPath -Name "DefaultUsername" -Value $Username
Set-ItemProperty -Path $RegPath -Name "DefaultPassword" -Value $Password
Set-ItemProperty -Path $RegPath -Name "DefaultDomainName" -Value $Domain

# Optional: Set number of times to automatically logon (0 = infinite)
Set-ItemProperty -Path $RegPath -Name "AutoLogonCount" -Value "0"