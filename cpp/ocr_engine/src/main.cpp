#include "ocr_pipeline.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

namespace {

std::string json_escape(const std::string& input) {
    std::ostringstream oss;
    for (char ch : input) {
        switch (ch) {
            case '"':
                oss << "\\\"";
                break;
            case '\\':
                oss << "\\\\";
                break;
            case '\n':
                oss << "\\n";
                break;
            case '\r':
                oss << "\\r";
                break;
            case '\t':
                oss << "\\t";
                break;
            default:
                oss << ch;
                break;
        }
    }
    return oss.str();
}

void print_usage() {
    std::cout << "Usage: ocr_trt_runner --input-dir <dir> --output-json <file> [--model-dir <dir>] [--allow-placeholder]\n";
}

}  // namespace

int main(int argc, char** argv) {
    std::filesystem::path input_dir;
    std::filesystem::path output_json;
    std::filesystem::path model_dir = "models";
    bool allow_placeholder = false;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--input-dir" && i + 1 < argc) {
            input_dir = argv[++i];
        } else if (arg == "--output-json" && i + 1 < argc) {
            output_json = argv[++i];
        } else if (arg == "--model-dir" && i + 1 < argc) {
            model_dir = argv[++i];
        } else if (arg == "--allow-placeholder") {
            allow_placeholder = true;
        } else if (arg == "--help" || arg == "-h") {
            print_usage();
            return 0;
        }
    }

    if (input_dir.empty() || output_json.empty()) {
        print_usage();
        return 2;
    }

    OcrPipeline pipeline;
    std::string error;
    if (!pipeline.initialize(model_dir, allow_placeholder, error)) {
        std::cerr << "Failed to initialize OCR pipeline: " << error << '\n';
        return 3;
    }

    const auto results = pipeline.run_directory(input_dir, error);
    if (!error.empty()) {
        std::cerr << "Failed to run OCR pipeline: " << error << '\n';
        return 4;
    }

    std::ofstream out(output_json);
    if (!out.is_open()) {
        std::cerr << "Failed to open output json: " << output_json << '\n';
        return 5;
    }

    out << "{\n";
    out << "  \"meta\": {\n";
    out << "    \"model_dir\": \"" << json_escape(model_dir.string()) << "\",\n";
    out << "    \"allow_placeholder\": " << (allow_placeholder ? "true" : "false") << "\n";
    out << "  },\n";
    out << "  \"results\": [\n";
    for (std::size_t i = 0; i < results.size(); ++i) {
        const auto& item = results[i];
        out << "    {\"file\": \"" << json_escape(item.file)
            << "\", \"text\": \"" << json_escape(item.text)
            << "\", \"confidence\": " << item.confidence << "}";
        if (i + 1 < results.size()) {
            out << ',';
        }
        out << '\n';
    }
    out << "  ]\n}\n";

    std::cout << "OCR completed. results=" << results.size() << '\n';
    return 0;
}
