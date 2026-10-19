"use client";

import { forwardRef, useImperativeHandle, useRef } from "react";

export interface PlayerHandle {
  seekTo: (seconds: number) => void;
}

/** youtube-nocookie embed controlled through the IFrame API's postMessage protocol (no extra script). */
export const YouTubePlayer = forwardRef<PlayerHandle, { videoId: string; title?: string }>(function YouTubePlayer({ videoId, title }, ref) {
  const frame = useRef<HTMLIFrameElement>(null);
  useImperativeHandle(ref, () => ({
    seekTo(seconds: number) {
      const w = frame.current?.contentWindow;
      if (!w) return;
      const send = (func: string, args: unknown[] = []) =>
        w.postMessage(JSON.stringify({ event: "command", func, args }), "https://www.youtube-nocookie.com");
      send("seekTo", [seconds, true]);
      send("playVideo");
      frame.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    },
  }));
  return (
    <div className="aspect-video w-full overflow-hidden rounded-lg bg-black">
      <iframe
        ref={frame}
        className="h-full w-full"
        src={`https://www.youtube-nocookie.com/embed/${videoId}?enablejsapi=1&rel=0&modestbranding=1`}
        title={title ?? "Source video"}
        allow="encrypted-media; picture-in-picture"
        allowFullScreen
        referrerPolicy="strict-origin-when-cross-origin"
      />
    </div>
  );
});
