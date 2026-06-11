import CoreGraphics
import ImageIO
import Foundation
import UniformTypeIdentifiers

let args = CommandLine.arguments
guard args.count >= 4 else { print("usage: wm <shot> <logo> <out> [alpha] [scale]"); exit(1) }
let alpha = args.count > 4 ? Double(args[4])! : 0.13
let scale = args.count > 5 ? Double(args[5])! : 0.30

func load(_ p: String) -> CGImage {
    let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: p) as CFURL, nil)!
    return CGImageSourceCreateImageAtIndex(src, 0, nil)!
}
let shot = load(args[1])
let logo = load(args[2])
let w = shot.width, h = shot.height
let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
ctx.draw(shot, in: CGRect(x: 0, y: 0, width: w, height: h))
let side = Double(min(w, h)) * scale
let lw = side, lh = side * Double(logo.height) / Double(logo.width)
ctx.setAlpha(CGFloat(alpha))
ctx.draw(logo, in: CGRect(x: (Double(w) - lw) / 2, y: (Double(h) - lh) / 2, width: lw, height: lh))
let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: args[3]) as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(dest, ctx.makeImage()!, nil)
CGImageDestinationFinalize(dest)
print("watermarked \(args[3])")
