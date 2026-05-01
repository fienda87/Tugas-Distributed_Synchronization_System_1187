$ErrorActionPreference = "Stop"
$OutDir = Join-Path $PSScriptRoot "certs"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$caKey = Join-Path $OutDir "ca.key"
$caCrt = Join-Path $OutDir "ca.crt"
$serverKey = Join-Path $OutDir "server.key"
$serverCsr = Join-Path $OutDir "server.csr"
$serverCrt = Join-Path $OutDir "server.crt"
$clientKey = Join-Path $OutDir "client.key"
$clientCsr = Join-Path $OutDir "client.csr"
$clientCrt = Join-Path $OutDir "client.crt"

openssl genrsa -out $caKey 4096
openssl req -x509 -new -nodes -key $caKey -sha256 -days 3650 -subj "/CN=dist-ca" -out $caCrt

openssl genrsa -out $serverKey 4096
openssl req -new -key $serverKey -subj "/CN=dist-server" -out $serverCsr
openssl x509 -req -in $serverCsr -CA $caCrt -CAkey $caKey -CAcreateserial -out $serverCrt -days 825 -sha256

openssl genrsa -out $clientKey 4096
openssl req -new -key $clientKey -subj "/CN=dist-client" -out $clientCsr
openssl x509 -req -in $clientCsr -CA $caCrt -CAkey $caKey -CAcreateserial -out $clientCrt -days 825 -sha256

"Generated CA, server, and client certs in $OutDir" | Write-Host
