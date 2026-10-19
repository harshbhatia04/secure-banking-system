param(
    [switch]$Tests,
    [switch]$Demo,
    [switch]$Web,
    [switch]$Groq,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$BankingArguments
)
if ($Groq -and -not $Web) {
    throw 'Use -Groq together with -Web.'
}
$clearGroqAfter = $false
if ($Groq) {
    if (-not $env:GROQ_API_KEY) {
        $storedGroqKey = Join-Path $PSScriptRoot 'data\.groq_key.dpapi'
        if (Test-Path -LiteralPath $storedGroqKey) {
            try {
                $secureGroqKey = (Get-Content -LiteralPath $storedGroqKey -Raw).Trim() | ConvertTo-SecureString
            } catch {
                throw 'The stored Groq key cannot be decrypted by this Windows user.'
            }
        } else {
            $secureGroqKey = Read-Host 'Enter a new Groq API key' -AsSecureString
        }
        $groqKeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureGroqKey)
        try {
            $env:GROQ_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($groqKeyPointer)
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($groqKeyPointer)
        }
        $clearGroqAfter = $true
    }
    if ([string]::IsNullOrWhiteSpace($env:GROQ_API_KEY)) {
        throw 'A Groq API key is required.'
    }
    if (-not $env:PBL_PORT) {
        $env:PBL_PORT = '5001'
    }
    Write-Host "Groq demo will open at http://127.0.0.1:$env:PBL_PORT/"
}
$bankingPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $bankingPython)) {
    $bankingPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
}
if (-not (Test-Path -LiteralPath $bankingPython)) {
    $bankingPython = 'python'
}
Push-Location $PSScriptRoot
try {
    if ($Tests) {
        & $bankingPython -m unittest discover -s tests -v
    } elseif ($Demo) {
        & $bankingPython (Join-Path $PSScriptRoot 'demo.py') @BankingArguments
    } elseif ($Web) {
        & $bankingPython (Join-Path $PSScriptRoot 'web_app.py')
    } else {
        & $bankingPython (Join-Path $PSScriptRoot 'app.py') @BankingArguments
    }
    $bankingExit = $LASTEXITCODE
} finally {
    Pop-Location
    if ($clearGroqAfter) {
        Remove-Item Env:GROQ_API_KEY -ErrorAction SilentlyContinue
    }
}
exit $bankingExit
