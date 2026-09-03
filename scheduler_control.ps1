param(
    [string]$TaskName = "RaceEngineer-History-Ingest"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = "Race Engineer · Scheduler"
$form.Size = New-Object System.Drawing.Size(520, 300)
$form.MinimumSize = New-Object System.Drawing.Size(520, 300)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(11, 17, 22)
$form.ForeColor = [System.Drawing.Color]::FromArgb(220, 231, 239)
$form.Font = New-Object System.Drawing.Font("Segoe UI", 10)

$title = New-Object System.Windows.Forms.Label
$title.Text = "Scheduler de telemetría"
$title.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 16)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(24, 20)
$form.Controls.Add($title)

$status = New-Object System.Windows.Forms.Label
$status.AutoSize = $false
$status.Location = New-Object System.Drawing.Point(26, 66)
$status.Size = New-Object System.Drawing.Size(460, 90)
$form.Controls.Add($status)

$note = New-Object System.Windows.Forms.Label
$note.Text = "Pausar detiene el ciclo activo y evita nuevas ejecuciones. Reanudar conserva todo el estado y habilita nuevamente la tarea."
$note.AutoSize = $false
$note.Location = New-Object System.Drawing.Point(26, 156)
$note.Size = New-Object System.Drawing.Size(460, 48)
$note.ForeColor = [System.Drawing.Color]::FromArgb(145, 166, 184)
$form.Controls.Add($note)

function Show-TaskError([string]$Message) {
    [System.Windows.Forms.MessageBox]::Show(
        $form,
        $Message,
        "Race Engineer",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
}

function Update-SchedulerStatus {
    try {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
        $status.Text = @"
Tarea: $TaskName
Estado: $($task.State)
Última ejecución: $($info.LastRunTime) · resultado $($info.LastTaskResult)
Próxima ejecución: $($info.NextRunTime)
"@
        if ($task.State -eq "Disabled") {
            $status.ForeColor = [System.Drawing.Color]::FromArgb(240, 198, 116)
            $pauseButton.Enabled = $false
            $resumeButton.Enabled = $true
        } else {
            $status.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 166)
            $pauseButton.Enabled = $true
            $resumeButton.Enabled = $false
        }
    } catch {
        $status.Text = "No se pudo consultar '$TaskName'.`r`n$($_.Exception.Message)"
        $status.ForeColor = [System.Drawing.Color]::FromArgb(255, 123, 114)
        $pauseButton.Enabled = $false
        $resumeButton.Enabled = $false
    }
}

$pauseButton = New-Object System.Windows.Forms.Button
$pauseButton.Text = "Pausar"
$pauseButton.Location = New-Object System.Drawing.Point(26, 214)
$pauseButton.Size = New-Object System.Drawing.Size(130, 34)
$pauseButton.Add_Click({
    try {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        if ($task.State -eq "Running") {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        }
        Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
        Update-SchedulerStatus
    } catch {
        Show-TaskError "No se pudo pausar el scheduler.`r`n`r`n$($_.Exception.Message)"
    }
})
$form.Controls.Add($pauseButton)

$resumeButton = New-Object System.Windows.Forms.Button
$resumeButton.Text = "Reanudar"
$resumeButton.Location = New-Object System.Drawing.Point(166, 214)
$resumeButton.Size = New-Object System.Drawing.Size(130, 34)
$resumeButton.Add_Click({
    try {
        Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
        Update-SchedulerStatus
    } catch {
        Show-TaskError "No se pudo reanudar el scheduler.`r`n`r`n$($_.Exception.Message)"
    }
})
$form.Controls.Add($resumeButton)

$refreshButton = New-Object System.Windows.Forms.Button
$refreshButton.Text = "Actualizar estado"
$refreshButton.Location = New-Object System.Drawing.Point(306, 214)
$refreshButton.Size = New-Object System.Drawing.Size(156, 34)
$refreshButton.Add_Click({ Update-SchedulerStatus })
$form.Controls.Add($refreshButton)

Update-SchedulerStatus
[void]$form.ShowDialog()
