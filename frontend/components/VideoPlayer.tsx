"use client";

export function VideoPlayer({ src }: { src: string }) {
  return (
    <div className="rounded-lg overflow-hidden border border-neutral-200 dark:border-neutral-800 bg-black">
      <video
        controls
        preload="metadata"
        className="w-full max-h-[70vh] bg-black"
        src={src}
      >
        Your browser doesn&apos;t support video playback.
      </video>
    </div>
  );
}
