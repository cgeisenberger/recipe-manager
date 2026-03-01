#!/usr/bin/env swift

import Foundation
import Vision
import AppKit

// MARK: - OCR Result Structure
struct OCRResult: Codable {
    let text: String
    let confidence: Float
    let imagePath: String
}

// MARK: - Main OCR Function
func performOCR(imagePath: String) {
    guard let image = NSImage(contentsOfFile: imagePath) else {
        print("Error: Could not load image from \(imagePath)")
        exit(1)
    }
    
    guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        print("Error: Could not convert NSImage to CGImage")
        exit(1)
    }
    
    let request = VNRecognizeTextRequest { (request, error) in
        if let error = error {
            print("Error: \(error.localizedDescription)")
            exit(1)
        }
        
        guard let observations = request.results as? [VNRecognizedTextObservation] else {
            print("Error: No text observations found")
            exit(1)
        }
        
        var extractedText = ""
        var totalConfidence: Float = 0.0
        
        for observation in observations {
            guard let topCandidate = observation.topCandidates(1).first else { continue }
            extractedText += topCandidate.string + "\n"
            totalConfidence += topCandidate.confidence
        }
        
        let averageConfidence = observations.isEmpty ? 0.0 : totalConfidence / Float(observations.count)
        
        let result = OCRResult(
            text: extractedText.trimmingCharacters(in: .whitespacesAndNewlines),
            confidence: averageConfidence,
            imagePath: imagePath
        )
        
        // Output as JSON
        let encoder = JSONEncoder()
        encoder.outputFormatting = .prettyPrinted
        
        if let jsonData = try? encoder.encode(result),
           let jsonString = String(data: jsonData, encoding: .utf8) {
            print(jsonString)
        } else {
            print("Error: Could not encode result to JSON")
            exit(1)
        }
        
        exit(0)
    }
    
    // Configure for accurate recognition
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["en-US", "de-DE"] // Add more languages as needed
    
    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    
    do {
        try handler.perform([request])
    } catch {
        print("Error: \(error.localizedDescription)")
        exit(1)
    }
    
    // Keep the script running until the request completes
    RunLoop.main.run()
}

// MARK: - Entry Point
guard CommandLine.arguments.count > 1 else {
    print("Usage: swift apple_ocr.swift <image_path>")
    exit(1)
}

let imagePath = CommandLine.arguments[1]
performOCR(imagePath: imagePath)
