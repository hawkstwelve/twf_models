type OverlayDecodeRequest = {
  id: number;
  url: string;
  cacheMode: RequestCache;
};

type OverlayDecodeSuccess = {
  id: number;
  url: string;
  bitmap: ImageBitmap;
};

type OverlayDecodeError = {
  id: number;
  url: string;
  error: string;
};

type OverlayDecodeResponse = OverlayDecodeSuccess | OverlayDecodeError;

function asErrorMessage(value: unknown): string {
  if (value instanceof Error && value.message) {
    return value.message;
  }
  return String(value || "Unknown overlay decode error");
}

self.onmessage = async (event: MessageEvent<OverlayDecodeRequest>) => {
  const payload = event.data;
  const { id, url, cacheMode } = payload;

  try {
    if (typeof createImageBitmap !== "function") {
      throw new Error("Worker createImageBitmap is unavailable");
    }

    const response = await fetch(url, {
      mode: "cors",
      credentials: "omit",
      cache: cacheMode,
    });
    if (!response.ok) {
      throw new Error(`Failed to fetch overlay bitmap (${response.status} ${response.statusText}) for ${url}`);
    }

    const blob = await response.blob();
    const bitmap = await createImageBitmap(blob);
    const message: OverlayDecodeResponse = { id, url, bitmap };
    (self as any).postMessage(message, [bitmap]);
  } catch (error) {
    const message: OverlayDecodeResponse = {
      id,
      url,
      error: asErrorMessage(error),
    };
    (self as any).postMessage(message);
  }
};
