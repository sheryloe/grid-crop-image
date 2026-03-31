#pragma once

#include <filesystem>
#include <string>
#include <vector>

struct OcrResult {
    std::string file;
    std::string text;
    float confidence;
};

class OcrPipeline {
public:
    OcrPipeline();
    bool initialize(const std::filesystem::path& model_dir, bool allow_placeholder, std::string& error);
    std::vector<OcrResult> run_directory(const std::filesystem::path& input_dir, std::string& error) const;

private:
    bool initialized_;
    bool placeholder_mode_;
};
