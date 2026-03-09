#!/usr/bin/env node

import http from 'node:http'
import net from 'node:net'
import process from 'node:process'
import { spawn, spawnSync } from 'node:child_process'

const host = process.env.PW_LIVEKIT_HOST || '127.0.0.1'
const livekitPort = Number(process.env.PW_LIVEKIT_PORT || '7880')
const readyPort = Number(process.env.PW_LIVEKIT_READY_PORT || '8788')
const dockerImage = process.env.PW_LIVEKIT_DOCKER_IMAGE || 'livekit/livekit-server'
const containerName = process.env.PW_LIVEKIT_CONTAINER_NAME || 'lsa-livekit-playwright'
const startTimeoutMs = Number(process.env.PW_LIVEKIT_START_TIMEOUT_MS || '120000')

let child = null
let ready = false
let shuttingDown = false
let fatalError = ''

function commandExists(command) {
  const result = spawnSync('bash', ['-lc', `command -v ${command}`], {
    stdio: 'ignore',
  })
  return result.status === 0
}

function dockerDaemonReady() {
  const result = spawnSync('docker', ['info'], {
    stdio: 'ignore',
  })
  return result.status === 0
}

function canConnect() {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port: livekitPort })

    const finish = (value) => {
      socket.removeAllListeners()
      socket.destroy()
      resolve(value)
    }

    socket.setTimeout(750)
    socket.once('connect', () => finish(true))
    socket.once('timeout', () => finish(false))
    socket.once('error', () => finish(false))
  })
}

async function waitForLiveKit() {
  const startedAt = Date.now()

  while (Date.now() - startedAt < startTimeoutMs) {
    if (await canConnect()) {
      return
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }

  throw new Error(
    `Timed out waiting for LiveKit on ${host}:${livekitPort} after ${startTimeoutMs}ms`
  )
}

function buildChildProcess() {
  if (commandExists('livekit-server')) {
    console.log('[livekit] starting local livekit-server binary')
    return spawn(
      'livekit-server',
      ['--dev', '--bind', host, '--port', String(livekitPort)],
      {
        stdio: 'inherit',
      }
    )
  }

  if (!commandExists('docker')) {
    throw new Error(
      'Neither livekit-server nor docker is available. Install livekit-server or start Docker.'
    )
  }

  if (!dockerDaemonReady()) {
    throw new Error(
      'Docker is installed but the daemon is not running. Start Docker/OrbStack or install livekit-server.'
    )
  }

  console.log('[livekit] starting dockerized livekit-server --dev')
  return spawn(
    'docker',
    [
      'run',
      '--rm',
      '--name',
      containerName,
      '-p',
      `${host}:${livekitPort}:7880`,
      '-p',
      `${host}:7881:7881/udp`,
      dockerImage,
      '--dev',
      '--bind',
      '0.0.0.0',
    ],
    {
      stdio: 'inherit',
    }
  )
}

const readinessServer = http.createServer((_request, response) => {
  if (ready) {
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(
      JSON.stringify({
        status: 'ok',
        host,
        livekitPort,
      })
    )
    return
  }

  response.writeHead(503, { 'Content-Type': 'application/json' })
  response.end(
    JSON.stringify({
      status: 'starting',
      error: fatalError || null,
      host,
      livekitPort,
    })
  )
})

function shutdown(signal) {
  shuttingDown = true
  console.log(`[livekit] shutting down (${signal})`)
  readinessServer.close()

  if (child && !child.killed) {
    child.kill('SIGTERM')
  }

  setTimeout(() => process.exit(0), 250)
}

process.on('SIGINT', () => shutdown('SIGINT'))
process.on('SIGTERM', () => shutdown('SIGTERM'))

readinessServer.listen(readyPort, host, async () => {
  try {
    if (await canConnect()) {
      ready = true
      console.log(`[livekit] reusing existing instance on ${host}:${livekitPort}`)
      return
    }

    child = buildChildProcess()
    child.once('exit', (code, signal) => {
      if (shuttingDown) {
        return
      }
      if (!ready) {
        fatalError = `LiveKit exited before becoming ready (code=${code}, signal=${signal})`
      }
      console.error(`[livekit] process exited (code=${code}, signal=${signal})`)
      process.exit(code ?? 1)
    })

    await waitForLiveKit()
    ready = true
    console.log(
      `[livekit] ready on ${host}:${livekitPort} (readiness server ${host}:${readyPort})`
    )
  } catch (error) {
    fatalError = error instanceof Error ? error.message : 'Unknown LiveKit startup error'
    console.error(`[livekit] ${fatalError}`)
    readinessServer.close()
    if (child && !child.killed) {
      child.kill('SIGTERM')
    }
    process.exit(1)
  }
})
