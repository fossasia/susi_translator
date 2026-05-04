
""" this module will accepts raw yt urls from streaming platform and 
extracts the HLS manifest url from the raw yt urls.
right now we are considering eventyay of FOSSASIA as a source for the streams
so as the youtube streams are the primary source of streams or eventyay 
we are considering that for now """



import logging
import subprocess
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

#enums
class StreamType(str, Enum):
    HLS= "hls"
    NATIVE = "native"
    YOUTUBE= "youtube"
    VIMEO = "vimeo"
    #BBB= "bigbluebutton"
    #JANUS = "janus"
    ZOOM = "zoom"
    IFRAME = "iframe"

class TapMethod(str, Enum):
    FFMPEG_HLS= "ffmpeg_hls"
    #BBB_HOOK= "bbb_hook"
    #JANUS_RTP = "janus_rtp"
    UNSUPPORTED = "unsupported"

#result and error types
@dataclass
class ResolvedStream:
    session_id:str
    stream_type:StreamType
    tap_method:TapMethod
    manifest_url:str                    
    original_url:str                    
    cached:bool = False           
    extra:dict = field(default_factory=dict)

    def is_supported(self) -> bool:
        return self.tap_method != TapMethod.UNSUPPORTED


class UnsupportedStreamError(Exception):
    """Raised when the stream type cannot be tapped server-side."""
    def __init__(self, stream_type: str, url: str):
        self.stream_type = stream_type
        self.url = url
        super().__init__(
            f"Stream type '{stream_type}' is not supported for server-side audio "
        )


class ResolutionError(Exception):
    """Raised when ytdlp fails to extract a manifest URL."""


#URL resolver
class URLResolver:
    """
    Resolves stream_url and stream_type into a HLS manifest.
    """
    #types of streams supported by the resolver
    # stream_types that map directly to FFmpeg HLS
    _DIRECT_HLS_TYPES = {StreamType.HLS, StreamType.NATIVE}
    
    # stream_types that need yt-dlp to unwrap the real manifest
    _YTDLP_TYPES = {StreamType.YOUTUBE, StreamType.VIMEO}

    #stream_types that are untappable server-side
    _UNSUPPORTED_TYPES = {StreamType.ZOOM, StreamType.IFRAME}

    def __init__(self,ytdlp_binary: str = "yt-dlp"):

        self._ytdlp_binary = ytdlp_binary
        self._manifest_cache: dict[str, str] = {}  


    def resolve(self,stream_url:  str,stream_type: str,session_id:  str) -> ResolvedStream:
        """
        Resolve a stream URL into a tap-ready manifest URL
        Returns a ResolvedStream with manifest_url and tap_method populated
        """
        try:
            stype = StreamType(stream_type.lower())
        except ValueError:
            raise ValueError(
                f"Unrecognised stream_type '{stream_type}'. "
                f"Valid values: {[e.value for e in StreamType]}"
            )

        logger.info("Resolving stream: session=%s type=%s url=%s",session_id, stype.value, stream_url)

        #unsupported streams
        if stype in self._UNSUPPORTED_TYPES:
            return self._unsupported(stream_url, stype, session_id)

        #direct HLS streams
        if stype in self._DIRECT_HLS_TYPES:
            return self._direct_hls(stream_url, stype, session_id)

        #yt-dlp streams
        if stype in self._YTDLP_TYPES:
            return self._resolve_via_ytdlp(stream_url, stype, session_id)

        #should never reach here as sets above are exhaustive
        raise ValueError(f"Unhandled stream type: {stype}")





    def invalidate(self, session_id: str) -> None:
        """
        Removes the cached manifest URL for a session, 
        when a session stops or when StreamSchedule 
        changes mid-event.
        """
        removed = self._manifest_cache.pop(session_id, None)
        if removed:
            logger.info("Cache invalidated session=%s", session_id)




    def is_cached(self, session_id: str) -> bool:
        """Return True if a manifest URL is already cached for this session."""
        return session_id in self._manifest_cache




    #resolution paths
    def _direct_hls(self,stream_url: str,stype: StreamType,session_id: str) -> ResolvedStream:
        """
        HLS and native streams are already tap-ready
        no yt-dlp call needed pass the URL straight to FFmpeg.
        """
        logger.info("Direct HLS tap session=%s manifest=%s", session_id, stream_url)
        return ResolvedStream(
            session_id=session_id,
            stream_type=stype,
            tap_method=TapMethod.FFMPEG_HLS,
            manifest_url=stream_url,
            original_url=stream_url,
            cached=False,
        )

    def _resolve_via_ytdlp(self,page_url: str,stype: StreamType,session_id: str,) -> ResolvedStream:
        """
        As YouTube and Vimeo provide human facing watch pages as 
        stream_url, we use yt-dlp to extract the real HLS manifest URL
        """
        #cache hit
        if session_id in self._manifest_cache:
            cached_url = self._manifest_cache[session_id]
            logger.info("Cache hit session=%s manifest=%s", session_id, cached_url)
            return ResolvedStream(
                session_id=session_id,
                stream_type=stype,
                tap_method=TapMethod.FFMPEG_HLS,
                manifest_url=cached_url,
                original_url=page_url,
                cached=True,
            )

        #cache miss
        logger.info("Running yt-dlp session=%s page_url=%s", session_id, page_url)
        manifest_url = self._run_ytdlp(page_url)

        #store in cache
        self._manifest_cache[session_id] = manifest_url
        logger.info("yt-dlp resolved and cached session=%s manifest=%s", session_id, manifest_url)

        return ResolvedStream(
            session_id=session_id,
            stream_type=stype,
            tap_method=TapMethod.FFMPEG_HLS,
            manifest_url=manifest_url,
            original_url=page_url,
            cached=False,
        )

    def _run_ytdlp(self, page_url: str) -> str:
        """
         yt-dlp is run as a subprocess to extract the best audio HLS manifest URL
        """

        if not page_url.startswith(("http://", "https://")):
            raise ResolutionError(f"Invalid URL protocol: {page_url}")

        cmd = [
            sys.executable, "-m", "yt_dlp",
            "-f", "bestaudio/best",
            "--no-playlist",
            "--no-warnings",
            "-J",
            page_url,
        ]

        try:
            # sourcery skip: dangerous-subprocess-use-audit
            # subprocess.run with a list of arguments is safe from shell injection.
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            raise ResolutionError(f"yt-dlp timed out after 15 seconds for URL: {page_url}")
        except FileNotFoundError:
            raise ResolutionError(f"yt-dlp binary not found at '{self._ytdlp_binary}'.")

        if result.returncode != 0:
            raise ResolutionError(f"yt-dlp exited with code {result.returncode} for URL: {page_url}. stderr: {result.stderr.strip()}")

        try:
            info = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise ResolutionError(f"yt-dlp returned invalid JSON for URL: {page_url}. Parse error: {e}")

        #finding a format with HLS protocol
        manifest_url = self._extract_hls_from_info(info)

        #fallback to the top-level 'url' field
        if not manifest_url:
            manifest_url = info.get("url")

        if not manifest_url:
            raise ResolutionError(f"yt-dlp could not extract a usable stream URL for: {page_url}. The video may be unavailable, private, or geo-restricted.")

        return manifest_url

    def _extract_hls_from_info(self, info: dict) -> Optional[str]:
        """
        extracting from the yt-dlp dictionary the best HLS audio format
        """
        formats = info.get("formats", [])
        if not formats:
            return None

        #audio only HLS
        for fmt in reversed(formats): #reversed for highest quality last in yt-dlp
            protocol = fmt.get("protocol", "")
            vcodec = fmt.get("vcodec", "")
            url = fmt.get("url", "")
            if "m3u8" in protocol and vcodec in ("none", ""):
                return url

        #any HLS format, FFmpeg will demux audio
        for fmt in reversed(formats):
            protocol = fmt.get("protocol", "")
            url = fmt.get("url", "")
            if "m3u8" in protocol and url:
                return url

        return None

    # def _future_tap(
    #     self,
    #     stream_url: str,
    #     stype: StreamType,
    #     session_id: str,
    # ) -> ResolvedStream:
    #     """
    #     BBB and Janus require their own tap mechanisms (not yet implemented).
    #     Returns a ResolvedStream with tap_method set to the appropriate future
    #     method so the orchestrator can route to the correct handler when ready.
    #     """
    #     tap = TapMethod.BBB_HOOK if stype == StreamType.BBB else TapMethod.JANUS_RTP
    #     logger.warning(
    #         "Stream type '%s' tap not yet implemented | session=%s",
    #         stype.value, session_id
    #     )
    #     return ResolvedStream(
    #         session_id=session_id,
    #         stream_type=stype,
    #         tap_method=tap,
    #         manifest_url="",
    #         original_url=stream_url,
    #         extra={"note": "tap implementation pending"},
    #     )

    def _unsupported(
        self,
        stream_url: str,
        stype: StreamType,
        session_id: str,
    ) -> ResolvedStream:
        """
        Zoom and iframe sources cannot be tapped server-side.
        """
        logger.error(
            "Unsupported stream type '%s' | session=%s url=%s",
            stype.value, session_id, stream_url
        )
        raise UnsupportedStreamError(stream_type=stype.value, url=stream_url)