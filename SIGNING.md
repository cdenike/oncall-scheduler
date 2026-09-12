# Signing the Windows build

Windows names the publisher of a program it is asked to run. Until the file
carries an Authenticode signature that name is "Unknown publisher", and
SmartScreen adds a blue "Windows protected your PC" panel over the top of it.

Nothing else in the build changes that. The version resource the build writes
does name Caden DeNike, and Windows shows it in the file's Properties -- but
the prompt reads the signature and only the signature, so an unsigned file
with a perfect version resource still says unknown. A signature is the only
fix.

There are three ways to get one, and which to use depends on who runs the
program.

## Handed round an office

Make a certificate, sign with it, and tell those machines to trust it. Free,
takes ten minutes, and the prompt names the publisher from then on.

On the machine that does the signing, once:

    powershell -ExecutionPolicy Bypass -File tools\sign.ps1 -Make

That writes `OnCallScheduler-publisher.cer`, which carries the public half
only -- the private key stays in that machine's certificate store, so the
`.cer` is safe to pass around and useless for signing.

Then on every machine that should see the name, as an administrator:

    certutil -addstore -f Root OnCallScheduler-publisher.cer
    certutil -addstore -f TrustedPublisher OnCallScheduler-publisher.cer

On a domain, the same two stores are a Group Policy setting
(Computer Configuration > Windows Settings > Security Settings >
Public Key Policies) and reach every machine at once.

Sign each build with:

    powershell -ExecutionPolicy Bypass -File tools\sign.ps1 dist\OnCallScheduler.exe

A machine that has not been told to trust the certificate is no worse off than
before: it sees an unsigned-looking file and warns, exactly as it does today.

## Downloaded from the internet

A stranger's machine will not have been told to trust anything, so the
certificate has to come from an authority Windows already trusts. Since June
2023 the private key for one must live in hardware -- a USB token, or a
service that holds it for you -- which rules out simply keeping a `.pfx` on a
laptop.

**Azure Artifact Signing** (until recently called Trusted Signing) is the
cheapest way in for one person: $9.99 a month, Microsoft holds the key, and it
issues a short-lived certificate per signature. Individual developers can
enrol -- the three-years-of-trading rule applies to organisations, not to
people. It needs a US or Canadian address, an Azure subscription whose billing
account type is Individual, and a government ID checked through Microsoft's
verifier. The certificate's common name is the legal name from that billing
account, so it must read exactly as the name the prompt should show; city,
state and country appear on the certificate too, street address and email do
not. Validation is usually quick for an individual, up to twenty business days
if documents are asked for.

Set these as repository secrets and every tagged build signs itself:

| Secret | What it is |
| --- | --- |
| `SIGNING_ENDPOINT` | the account's regional URI, e.g. `https://eus.codesigning.azure.net` |
| `SIGNING_ACCOUNT` | the signing account name |
| `SIGNING_PROFILE` | the certificate profile name |
| `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` | an app registration holding the **Artifact Signing Certificate Profile Signer** role (it was called Trusted Signing Certificate Profile Signer until the rename) |

In order, because each step needs the one before it:

1. **Check the name first.** The certificate takes its common name from the
   Azure billing account, not from anything typed into the signing form, and
   correcting it afterwards means starting validation again. [Cost Management
   + Billing](https://portal.azure.com/#view/Microsoft_Azure_GTM/ModernBillingMenuBlade)
   > Properties: the legal name there must read exactly as the Windows prompt
   should read, and the account type must be Individual.
2. [Register the `Microsoft.CodeSigning` provider and create the signing
   account](https://learn.microsoft.com/azure/artifact-signing/quickstart) --
   Basic SKU, in a region near you, whose endpoint URI becomes
   `SIGNING_ENDPOINT`.
3. **Identity validation**, on the account's Identity validations pane:
   Organization > Individual > New identity > Public. It sends you to an ID
   check done with a phone camera and the Microsoft Authenticator app. Have a
   passport or driving licence to hand. Certificate subject preview shows what
   will be on the certificate before you commit to it.
4. **Certificate profile** -- Public Trust, pointed at that validation. Its
   name becomes `SIGNING_PROFILE`, the account's `SIGNING_ACCOUNT`.
5. **An app registration** for the build to sign as: Microsoft Entra ID > App
   registrations > New registration, then a client secret. Its tenant, client
   and secret values are the three `AZURE_*` secrets.
6. **Give it the role**, on the certificate profile or the resource group:
   Access control (IAM) > Add role assignment > Artifact Signing Certificate
   Profile Signer. Signing fails with a permissions error without it, which is
   the usual first-time mistake. [The role tutorial has the
   detail.](https://learn.microsoft.com/azure/artifact-signing/tutorial-assign-roles)
7. **Put all six in the repository**, at Settings > Secrets and variables >
   Actions, and tag a release. The build's last Windows step prints the name
   the prompt will show.

**A certificate bought outright** -- an OV certificate from a commercial
authority, around $200-350 a year, on a token or in a cloud HSM -- works too,
and the build takes one as `WINDOWS_CERT_PFX` (the file, base64) and
`WINDOWS_CERT_PASSWORD`. Its advantage is that the certificate is yours for
the term; its cost is the hardware and the renewal.

EV certificates are no longer worth the premium for this. Until 2024 they
skipped the SmartScreen panel outright; that behaviour was removed, and an
EV-signed file now builds reputation the same way an OV-signed one does.

Certum's cheap open-source certificate is not usable here on two counts: its
publisher line is fixed to "Open Source Developer" followed by the name, and
it may not sign anything distributed commercially.

## Reputation, either way

A signature fixes the publisher name immediately. The blue SmartScreen panel
is separate: it fades once enough people have run files signed with that
certificate, and Microsoft does not publish the threshold. Signing every
release with the same certificate is what accumulates it, so a certificate
changed often never builds any.
