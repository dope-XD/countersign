/**
 * Two-way 8 kHz mu-law audio over a websocket, the way a phone line carries it.
 * Used by the caller softphone and the agent console.
 */
export type Source = { kind: 'mic'; deviceId?: string } | { kind: 'file'; file: File; loop?: boolean } | { kind: 'none' }

export class PhoneAudio {
  ctx: AudioContext | null = null
  capture: AudioWorkletNode | null = null
  playback: AudioWorkletNode | null = null
  stream: MediaStream | null = null
  fileNode: AudioBufferSourceNode | null = null
  onFrame: (b: ArrayBuffer) => void = () => {}
  onLevel: (l: number) => void = () => {}
  onFileEnded: () => void = () => {}

  async start(source: Source, monitorFile = true) {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    this.ctx = new AC()
    await this.ctx.audioWorklet.addModule('/worklets/capture.js')
    await this.ctx.audioWorklet.addModule('/worklets/playback.js')
    this.capture = new AudioWorkletNode(this.ctx, 'capture-8k')
    this.capture.port.onmessage = (e) => {
      if (e.data instanceof ArrayBuffer) this.onFrame(e.data)
      else if (e.data && typeof e.data.level === 'number') this.onLevel(e.data.level)
    }
    // The capture node has to be pulled by the graph, so route it into a muted gain.
    const sink = this.ctx.createGain()
    sink.gain.value = 0
    this.capture.connect(sink).connect(this.ctx.destination)

    this.playback = new AudioWorkletNode(this.ctx, 'playback-8k', { outputChannelCount: [1] })
    this.playback.connect(this.ctx.destination)
    await this.setSource(source, monitorFile)
    if (this.ctx.state === 'suspended') await this.ctx.resume()
  }

  async setSource(source: Source, monitorFile = true) {
    if (!this.ctx || !this.capture) return
    this.stopSource()
    if (source.kind === 'mic') {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          deviceId: source.deviceId ? { exact: source.deviceId } : undefined,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      })
      this.ctx.createMediaStreamSource(this.stream).connect(this.capture)
    } else if (source.kind === 'file') {
      const buf = await this.ctx.decodeAudioData(await source.file.arrayBuffer())
      const node = this.ctx.createBufferSource()
      node.buffer = buf
      node.loop = !!source.loop
      node.connect(this.capture)
      if (monitorFile) node.connect(this.ctx.destination)
      node.onended = () => this.onFileEnded()
      node.start()
      this.fileNode = node
    }
  }

  stopSource() {
    this.stream?.getTracks().forEach((t) => t.stop())
    this.stream = null
    try {
      this.fileNode?.stop()
    } catch {
      /* already stopped */
    }
    this.fileNode = null
  }

  play(bytes: ArrayBuffer) {
    this.playback?.port.postMessage(bytes, [bytes])
  }

  mute(m: boolean) {
    this.capture?.port.postMessage({ muted: m })
  }

  async stop() {
    this.stopSource()
    await this.ctx?.close().catch(() => {})
    this.ctx = null
  }
}

export async function listMics(): Promise<MediaDeviceInfo[]> {
  try {
    const d = await navigator.mediaDevices.enumerateDevices()
    return d.filter((x) => x.kind === 'audioinput')
  } catch {
    return []
  }
}
