/**
 * Encode a video frame from a canvas as a JPEG blob with the binary protocol header.
 * Protocol: 0x01 + JPEG bytes (video), 0x02 + PCM bytes (audio)
 */
export async function encodeVideoFrame(
  canvas: HTMLCanvasElement,
  quality: number = 0.7
): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      async (blob) => {
        if (!blob) {
          reject(new Error('Failed to create blob from canvas'))
          return
        }
        const arrayBuffer = await blob.arrayBuffer()
        const header = new Uint8Array([0x01])
        const combined = new Uint8Array(1 + arrayBuffer.byteLength)
        combined.set(header)
        combined.set(new Uint8Array(arrayBuffer), 1)
        resolve(combined.buffer)
      },
      'image/jpeg',
      quality
    )
  })
}

export function encodeAudioChunk(pcmData: Int16Array): ArrayBuffer {
  const header = new Uint8Array([0x02])
  const audioBytes = new Uint8Array(pcmData.buffer)
  const combined = new Uint8Array(1 + audioBytes.byteLength)
  combined.set(header)
  combined.set(audioBytes, 1)
  return combined.buffer
}
