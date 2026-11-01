// Local audio/OCR evidence for the isolated video worker. No browser or network.
import Foundation
import AVFoundation
import SoundAnalysis
import Vision
import ImageIO

struct Frame: Decodable { let path: String; let at: Double }
struct Manifest: Decodable { let audio_path: String; let frames: [Frame] }
enum ProbeError: Error { case invalidInput, incompleteAudio, unreadableFrame }

final class Observer: NSObject, SNResultsObserving {
    var windows = [[String: Any]]()
    var failure: Error?
    var complete = false
    func request(_ request: SNRequest, didProduce result: SNResult) {
        guard let result = result as? SNClassificationResult else { return }
        let important = Set(["music", "singing", "speech", "rapping", "humming", "silence"])
        let classes = result.classifications.filter { important.contains($0.identifier) }
        windows.append([
            "at": result.timeRange.start.seconds,
            "duration": result.timeRange.duration.seconds,
            "scores": Dictionary(uniqueKeysWithValues: classes.map { ($0.identifier, $0.confidence) }),
            "top": result.classifications.prefix(5).map { ["label": $0.identifier, "confidence": $0.confidence] as [String: Any] }
        ])
    }
    func request(_ request: SNRequest, didFailWithError error: Error) { failure = error }
    func requestDidComplete(_ request: SNRequest) { complete = true }
}

func output(_ object: [String: Any]) throws {
    let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
}

do {
    let request = try SNClassifySoundRequest(classifierIdentifier: .version1)
    request.windowDuration = CMTime(seconds: 1.5, preferredTimescale: 48000)
    request.overlapFactor = 0.5
    if CommandLine.arguments.count == 2 && CommandLine.arguments[1] == "--self-check" {
        try output(["version": 1, "audio_backend": "Apple SoundAnalysis version1",
                    "ocr_backend": "Apple Vision", "classes": request.knownClassifications])
    } else {
        guard CommandLine.arguments.count == 2 else { throw ProbeError.invalidInput }
        let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        guard data.count < 200000 else { throw ProbeError.invalidInput }
        let manifest = try JSONDecoder().decode(Manifest.self, from: data)
        guard !manifest.frames.isEmpty && manifest.frames.count <= 300 else { throw ProbeError.invalidInput }
        let observer = Observer()
        let analyzer = try SNAudioFileAnalyzer(url: URL(fileURLWithPath: manifest.audio_path))
        try analyzer.add(request, withObserver: observer)
        analyzer.analyze()
        if let failure = observer.failure { throw failure }
        guard observer.complete && !observer.windows.isEmpty else { throw ProbeError.incompleteAudio }
        var frames = [[String: Any]]()
        for frame in manifest.frames {
            try autoreleasepool {
                let url = URL(fileURLWithPath: frame.path)
                guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
                      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { throw ProbeError.unreadableFrame }
                let ocr = VNRecognizeTextRequest()
                ocr.recognitionLevel = .accurate
                ocr.recognitionLanguages = ["en-US", "zh-Hans"]
                ocr.usesLanguageCorrection = false
                ocr.preferBackgroundProcessing = true
                try VNImageRequestHandler(cgImage: image).perform([ocr])
                let texts: [[String: Any]] = (ocr.results ?? []).prefix(80).compactMap { observation in
                    guard let text = observation.topCandidates(1).first else { return nil }
                    let b = observation.boundingBox
                    return ["text": String(text.string.prefix(300)), "confidence": Double(text.confidence),
                            "box": [b.minX, 1 - b.maxY, b.width, b.height]]
                }
                frames.append(["at": frame.at, "texts": texts])
            }
        }
        try output(["version": 1, "audio_backend": "Apple SoundAnalysis version1",
                    "audio_complete": observer.complete, "windows": observer.windows,
                    "ocr_backend": "Apple Vision", "frames": frames])
    }
} catch {
    FileHandle.standardError.write(Data("local media analysis failed: \(type(of: error))\n".utf8))
    exit(1)
}
