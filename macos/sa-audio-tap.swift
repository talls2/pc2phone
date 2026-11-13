import AVFoundation
import CoreMedia
import Foundation
import ScreenCaptureKit

final class Tap: NSObject, SCStreamOutput, SCStreamDelegate {
    var stream: SCStream?
    let queue = DispatchQueue(label: "speaker-anywhere.audio")

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
        guard let display = content.displays.first else {
            throw NSError(domain: "tap", code: 1, userInfo: [NSLocalizedDescriptionKey: "no display found"])
        }
        let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.sampleRate = 48000
        config.channelCount = 2
        config.width = 2
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        let s = SCStream(filter: filter, configuration: config, delegate: self)
        try s.addStreamOutput(self, type: .audio, sampleHandlerQueue: queue)
        try await s.startCapture()
        stream = s
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, sampleBuffer.isValid else { return }
        let frames = CMSampleBufferGetNumSamples(sampleBuffer)
        if frames == 0 { return }

        let listSize = MemoryLayout<AudioBufferList>.size + 2 * MemoryLayout<AudioBuffer>.size
        let raw = UnsafeMutableRawPointer.allocate(byteCount: listSize, alignment: 16)
        defer { raw.deallocate() }
        let list = raw.bindMemory(to: AudioBufferList.self, capacity: 1)
        var block: CMBlockBuffer?
        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer,
            bufferListSizeNeededOut: nil,
            bufferListOut: list,
            bufferListSize: listSize,
            blockBufferAllocator: nil,
            blockBufferMemoryAllocator: nil,
            flags: kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment,
            blockBufferOut: &block)
        if status != noErr { return }

        let buffers = UnsafeMutableAudioBufferListPointer(list)
        var out = [Int16](repeating: 0, count: frames * 2)

        func toInt16(_ v: Float) -> Int16 {
            let c = max(-1.0, min(1.0, v))
            return Int16(c * 32767.0)
        }

        if buffers.count >= 2 {
            guard let lp = buffers[0].mData?.assumingMemoryBound(to: Float.self),
                  let rp = buffers[1].mData?.assumingMemoryBound(to: Float.self) else { return }
            for i in 0..<frames {
                out[2 * i] = toInt16(lp[i])
                out[2 * i + 1] = toInt16(rp[i])
            }
        } else if buffers.count == 1 {
            guard let p = buffers[0].mData?.assumingMemoryBound(to: Float.self) else { return }
            let channels = Int(buffers[0].mNumberChannels)
            for i in 0..<frames {
                if channels >= 2 {
                    out[2 * i] = toInt16(p[i * channels])
                    out[2 * i + 1] = toInt16(p[i * channels + 1])
                } else {
                    let v = toInt16(p[i])
                    out[2 * i] = v
                    out[2 * i + 1] = v
                }
            }
        } else {
            return
        }

        out.withUnsafeBytes { bytes in
            _ = fwrite(bytes.baseAddress, 1, bytes.count, stdout)
        }
        fflush(stdout)
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        FileHandle.standardError.write(Data("capture stopped: \(error.localizedDescription)\n".utf8))
        exit(1)
    }
}

let tap = Tap()
Task {
    do {
        try await tap.start()
    } catch {
        FileHandle.standardError.write(Data(
            "could not start audio capture: \(error.localizedDescription). Allow Speaker Anywhere under System Settings > Privacy & Security > Screen & System Audio Recording, then try again.\n".utf8))
        exit(1)
    }
}
RunLoop.main.run()
