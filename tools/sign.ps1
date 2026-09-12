<#
.SYNOPSIS
    Sign OnCallScheduler.exe on this machine.

.DESCRIPTION
    Windows names the publisher of a program it is asked to run, and says
    "unknown publisher" until the file carries an Authenticode signature. This
    signs one with a certificate of your own making.

    A certificate of your own making is trusted by the machines you tell to
    trust it, and by no others. That is enough for a program handed round one
    office -- install the certificate once per machine and the prompt names
    the publisher from then on -- and not enough for a download from the
    internet, which needs a certificate from an authority Windows already
    trusts. SIGNING.md has that route.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\sign.ps1 -Make
    powershell -ExecutionPolicy Bypass -File tools\sign.ps1 dist\OnCallScheduler.exe

.NOTES
    Copyright (C) 2026 Caden DeNike. Free software under the GNU General
    Public License, version 3 or later, with no warranty. See LICENSE.
#>
param(
    [string] $Path = "dist\OnCallScheduler.exe",
    [string] $Publisher = "Caden DeNike",
    # Make the certificate, export it for the machines that must trust it,
    # and stop.
    [switch] $Make,
    [string] $Export = "OnCallScheduler-publisher.cer"
)

$ErrorActionPreference = "Stop"

function Find-Certificate {
    Get-ChildItem Cert:\CurrentUser\My |
        Where-Object { $_.Subject -eq "CN=$Publisher" -and $_.NotAfter -gt (Get-Date) } |
        Sort-Object NotAfter -Descending | Select-Object -First 1
}

if ($Make) {
    $cert = New-SelfSignedCertificate -Type CodeSigningCert `
        -Subject "CN=$Publisher" -CertStoreLocation Cert:\CurrentUser\My `
        -KeyUsage DigitalSignature -KeyLength 3072 `
        -NotAfter (Get-Date).AddYears(5) `
        -HashAlgorithm SHA256
    Export-Certificate -Cert $cert -FilePath $Export -Type CERT | Out-Null
    Write-Host "Made a certificate for '$Publisher', good for five years."
    Write-Host "Thumbprint: $($cert.Thumbprint)"
    Write-Host ""
    Write-Host "Keep this machine: the private key lives in its certificate"
    Write-Host "store and is not in $Export."
    Write-Host ""
    Write-Host "On every machine that should see the name rather than a"
    Write-Host "warning, as an administrator, with $Export to hand:"
    Write-Host ""
    Write-Host "    certutil -addstore -f Root `"$Export`""
    Write-Host "    certutil -addstore -f TrustedPublisher `"$Export`""
    return
}

$cert = Find-Certificate
if (-not $cert) {
    throw "No code-signing certificate for '$Publisher' on this machine. Run with -Make first."
}
if (-not (Test-Path $Path)) { throw "No such file: $Path" }

# Timestamped, so the signature outlives the certificate rather than expiring
# with it.
Set-AuthenticodeSignature -FilePath $Path -Certificate $cert `
    -HashAlgorithm SHA256 `
    -TimestampServer "http://timestamp.digicert.com" | Out-Null

$sig = Get-AuthenticodeSignature $Path
$name = $sig.SignerCertificate.Subject -replace '^CN=([^,]+).*$', '$1'
Write-Host "Signed $Path."
Write-Host "Windows will name the publisher: $name"
if (-not $sig.TimeStamperCertificate) { throw "the signature was not timestamped" }
if ($sig.Status -ne "Valid" -and $sig.Status -ne "UnknownError") {
    Write-Host "Status: $($sig.Status) -- expected until this machine trusts the certificate."
}
