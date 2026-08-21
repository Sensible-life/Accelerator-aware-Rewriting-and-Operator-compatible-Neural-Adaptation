$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$downloadDirectory = Join-Path $repositoryRoot "models\downloads"

$models = @(
    @{
        Name = "mobilenetv2_a035_128_food101_qdq.onnx"
        Url = "https://media.githubusercontent.com/media/STMicroelectronics/stm32ai-modelzoo/main/image_classification/mobilenetv2/ST_pretrainedmodel_public_dataset/food101/mobilenetv2_a035_128_fft/mobilenetv2_a035_128_fft_qdq_w4_53.32%25_w8_46.68%25_a8_100%25_acc_64.61.onnx"
        Sha256 = "f998c183a0c117a18c10e1f8d4595e5456aeca9dc933c109ca8e795604188a61"
    },
    @{
        Name = "yolo26n_256_coco_person_qdq_int8.onnx"
        Url = "https://raw.githubusercontent.com/stm32-hotspot/ultralytics/main/examples/YOLOv8-STEdgeAI/stedgeai_models/object_detection/yolo26/yolo26_256_qdq_int8_od_coco-person-st.onnx"
        Sha256 = "8e3197754d64337db74bde0782293981a40d6a2dad1ebff405e323b81399282e"
    }
)

New-Item -ItemType Directory -Path $downloadDirectory -Force | Out-Null

foreach ($model in $models) {
    $destination = Join-Path $downloadDirectory $model.Name
    if (Test-Path -LiteralPath $destination) {
        $existingHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($existingHash -eq $model.Sha256) {
            Write-Host "Verified $($model.Name)"
            continue
        }
    }

    $partial = "$destination.part"
    & curl.exe -L --fail --retry 2 --output $partial $model.Url
    if ($LASTEXITCODE -ne 0) {
        throw "Download failed for $($model.Name) with exit code $LASTEXITCODE"
    }

    $downloadedHash = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($downloadedHash -ne $model.Sha256) {
        Remove-Item -LiteralPath $partial -Force
        throw "SHA-256 mismatch for $($model.Name): $downloadedHash"
    }

    Move-Item -LiteralPath $partial -Destination $destination -Force
    Write-Host "Downloaded and verified $($model.Name)"
}
