const paths: Record<string, string> = {
  mic: 'M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Zm-7 9a7 7 0 0 0 14 0M12 19v3',
  stop: 'M7 7h10v10H7z',
  volume: 'M4 9v6h4l5 4V5L8 9H4Zm12.5-1.5a5 5 0 0 1 0 9M19 5a9 9 0 0 1 0 14',
  mute: 'M4 9v6h4l5 4V5L8 9H4Zm12 0 5 6m0-6-5 6',
  close: 'M6 6l12 12M18 6 6 18',
  plus: 'M12 5v14M5 12h14',
  trash: 'M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13',
  play: 'M8 5v14l11-7z',
  pause: 'M8 5v14M16 5v14',
  chev: 'm6 9 6 6 6-6',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-13v4.5l3 2',
  news: 'M4 5h13v14H6a2 2 0 0 1-2-2V5Zm13 4h3v8a2 2 0 0 1-2 2M8 9h5M8 13h5M8 16h3',
  brain: 'M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3 2 2 0 0 0 2-2V5a1 1 0 0 0-2-1Zm6 0a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3 2 2 0 0 1-2-2V5a1 1 0 0 1 2-1Z',
  chip: 'M8 8h8v8H8zM5 9h3M5 15h3M16 9h3M16 15h3M9 5v3M15 5v3M9 16v3M15 16v3',
  clip: 'M21 11.5 12.5 20a5 5 0 0 1-7-7L14 4.5a3.5 3.5 0 0 1 5 5L10.5 18a2 2 0 0 1-3-3L15 7.5',
  file: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Zm0 0v5h5',
  download: 'M12 4v11m0 0-4-4m4 4 4-4M5 20h14',
  next: 'M6 5v14l9-7zM18 5v14',
  prev: 'M18 5v14L9 12zM6 5v14',
  external: 'M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5',
  gear: 'M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm7.4-2.2.1-1.3-.1-1.3 2-1.6-2-3.4-2.4 1a7.6 7.6 0 0 0-2.2-1.3L14.5 3h-4l-.4 2.4c-.8.3-1.5.8-2.2 1.3l-2.4-1-2 3.4 2 1.6-.1 1.3.1 1.3-2 1.6 2 3.4 2.4-1c.7.5 1.4 1 2.2 1.3l.4 2.4h4l.4-2.4c.8-.3 1.5-.8 2.2-1.3l2.4 1 2-3.4-2-1.6Z',
  history: 'M3 12a9 9 0 1 0 3-6.7M3 4v4h4M12 7v5l3 2',
  plug: 'M9 2v5M15 2v5M6 7h12v4a6 6 0 0 1-12 0V7Zm6 10v5',
  sliders: 'M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4',
  ear: 'M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4',
}

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={paths[name]} />
    </svg>
  )
}
