import type { MediaProvider, SessionInfo } from '@/lib/types'
import { MEDIA_PROVIDER_OVERRIDE } from '@/lib/constants'

export function resolveMediaProvider(
  sessionInfo: Pick<SessionInfo, 'media_provider'> | null
): MediaProvider {
  if (MEDIA_PROVIDER_OVERRIDE === 'livekit') {
    return 'livekit'
  }

  if (MEDIA_PROVIDER_OVERRIDE === 'custom_webrtc') {
    return 'custom_webrtc'
  }

  return sessionInfo?.media_provider ?? 'custom_webrtc'
}
