# Export HWPX files to PDF with Hangul, auto-allowing every file read/write/access prompt.
#  1) RegisterModule for the file-path security module (silently ignored if not installed)
#  2) SetMessageBoxMode: auto-answer Hangul message boxes with OK/Yes
#  3) Watchdog job: any Hangul dialog that still appears gets its "모두 허용 / 접근 허용 / 허용 / 확인 / 예" button clicked
# usage (PowerShell): & ([scriptblock]::Create((Get-Content -Raw -Encoding UTF8 hwp_to_pdf.ps1))) -Files a.hwpx,b.hwpx -PdfDir out
param([string[]]$Files, [string]$PdfDir)
New-Item -ItemType Directory -Force $PdfDir | Out-Null
$watch = Start-Job -ScriptBlock {
    Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
    $names = '모두 허용', '접근 허용', '허용', '확인', '예(&Y)', '예', 'OK', 'Yes'
    while ($true) {
        foreach ($p in Get-Process Hwp -ErrorAction SilentlyContinue) {
            $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $p.Id)
            foreach ($w in [System.Windows.Automation.AutomationElement]::RootElement.FindAll('Children', $cond)) {
                foreach ($n in $names) {
                    $b = $w.FindFirst('Descendants', (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $n)))
                    if ($b -and $b.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button) {
                        ($b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)).Invoke(); break
                    }
                }
            }
        }
        Start-Sleep -Milliseconds 400
    }
}
$h = New-Object -ComObject HWPFrame.HwpObject
try {
    $null = $h.RegisterModule('FilePathCheckDLL', 'FilePathCheckerModule')
    $null = $h.SetMessageBoxMode(0x00010000 -bor 0x00000010 -bor 0x00000001)   # Yes / OK automatically
    $h.XHwpWindows.Item(0).Visible = $false
    foreach ($f in $Files) {
        $item = Get-Item -LiteralPath $f
        if (-not $h.Open($item.FullName, 'HWPX', 'forceopen:true;versionwarning:false;suspendpassword:true')) { throw "open failed: $f" }
        $pdf = Join-Path $PdfDir ($item.BaseName + '.pdf')
        if (-not $h.SaveAs($pdf, 'PDF', '')) { throw "pdf failed: $f" }
        '{0} | pages {1}' -f $item.Name, $h.PageCount
        $h.Clear(1)
    }
} finally { $h.Quit(); Stop-Job $watch; Remove-Job $watch -Force }
