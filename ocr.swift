import Foundation
import Vision
import AppKit

// consumer OCR helper — macOS Vision framework (Live Text). Genuinely local:
// no network, no API keys. Compiled once by ocr.py (cached binary), invoked
// per image: `consumer-ocr <image-path>` prints recognized text to stdout.
let arg = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : ""
guard !arg.isEmpty else { exit(2) }
guard let img = NSImage(contentsOfFile: arg),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    exit(3)
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
if #available(macOS 13.0, *) {
    if let lang = Locale.preferredLanguages.first?.prefix(2) {
        request.recognitionLanguages = [String(lang)]
    }
}
let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do {
    try handler.perform([request])
    let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    print(lines.joined(separator: "\n"))
} catch {
    exit(4)
}