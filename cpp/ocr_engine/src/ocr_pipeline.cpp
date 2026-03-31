#include "ocr_pipeline.hpp"

#include <algorithm>
#include <cctype>
#include <fstream>

namespace {

bool is_supported_image(const std::filesystem::path& path) {
    if (!path.has_extension()) {
        return false;
    }

    std::string ext = path.extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });

    return ext == ".png" || ext == ".jpg" || ext == ".jpeg" || ext == ".bmp" || ext == ".webp";
}

}  // namespace

OcrPipeline::OcrPipeline() : initialized_(false), placeholder_mode_(false) {}

bool OcrPipeline::initialize(const std::filesystem::path& model_dir, bool allow_placeholder, std::string& error) {
    if (!std::filesystem::exists(model_dir)) {
        error = "model directory does not exist: " + model_dir.string();
        return false;
    }

    const auto detector_engine = model_dir / "detector.engine";
    const auto recognizer_engine = model_dir / "recognizer.engine";

    const bool has_detector = std::filesystem::exists(detector_engine) && std::filesystem::file_size(detector_engine) > 0;
    const bool has_recognizer =
        std::filesystem::exists(recognizer_engine) && std::filesystem::file_size(recognizer_engine) > 0;

    if (!has_detector || !has_recognizer) {
        if (!allow_placeholder) {
            error =
                "TensorRT engine files are missing. Required: detector.engine, recognizer.engine in " + model_dir.string();
            return false;
        }
        placeholder_mode_ = true;
    }

#ifdef USE_TENSORRT
    if (!placeholder_mode_) {
        // TODO: TensorRT runtime/engine initialization.
        // - load detector.engine / recognizer.engine
        // - create execution context and I/O bindings
    }
#endif

    initialized_ = true;
    return true;
}

std::vector<OcrResult> OcrPipeline::run_directory(const std::filesystem::path& input_dir, std::string& error) const {
    std::vector<OcrResult> results;

    if (!initialized_) {
        error = "pipeline is not initialized";
        return results;
    }

    if (!std::filesystem::exists(input_dir)) {
        error = "input directory does not exist: " + input_dir.string();
        return results;
    }

    for (const auto& entry : std::filesystem::directory_iterator(input_dir)) {
        if (!entry.is_regular_file()) {
            continue;
        }

        const auto& file_path = entry.path();
        if (!is_supported_image(file_path)) {
            continue;
        }

        OcrResult result;
        result.file = file_path.filename().string();

        if (placeholder_mode_) {
            result.text = "TRT_PLACEHOLDER_MODEL_NOT_READY";
            result.confidence = 0.01F;
        }
#ifdef USE_TENSORRT
        else {
            // TODO: 실제 TensorRT OCR 추론 결과로 교체.
            result.text = "TRT_OCR_READY_FOR_INFERENCE";
            result.confidence = 0.50F;
        }
#else
        if (!placeholder_mode_) {
            result.text = "OCR_READY_NO_TRT_BUILD";
            result.confidence = 0.30F;
        } else {
            result.text = "OCR_PLACEHOLDER";
            result.confidence = 0.10F;
        }
#endif

        results.push_back(result);
    }

    return results;
}
