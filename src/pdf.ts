import { GlobalWorkerOptions, getDocument, PDFDataRangeTransport, type PDFDocumentProxy, type RenderTask } from 'pdfjs-dist';
import pdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { readRange } from './api';

GlobalWorkerOptions.workerSrc = pdfWorker;

export async function openPdf(sourceId: string, bytes: number, token?: string) {
  const range = new PDFDataRangeTransport(bytes, new Uint8Array(await readRange({ bytes }, sourceId, 0, Math.min(bytes, 65536), token)));
  let readError: unknown;
  range.requestDataRange = (begin, end) => {
    // PDF.js can merge adjacent ranges. Deliver one contiguous block to its transport.
    void (async () => {
      const block = new Uint8Array(end - begin);
      for (let offset = begin; offset < end; offset += 8 * 1024 * 1024) {
        const part = await readRange({ bytes }, sourceId, offset, Math.min(end - offset, 8 * 1024 * 1024), token);
        block.set(new Uint8Array(part), offset - begin);
      }
      if (!task.destroyed) range.onDataRange(begin, block);
    })().catch(error => { readError = error; void task.destroy(); });
  };
  const task = getDocument({ range, disableAutoFetch: true, disableStream: true });
  try {
    const pdf = await task.promise;
    return { pdf, close: () => task.destroy() };
  } catch (error) {
    await task.destroy();
    throw readError ?? error;
  }
}

export async function renderPage(pdf: PDFDocumentProxy, ordinal: number, maxWidth: number, canvas: HTMLCanvasElement): Promise<RenderTask> {
  const page = await pdf.getPage(ordinal);
  const viewport = page.getViewport({ scale: maxWidth / page.getViewport({ scale: 1 }).width });
  canvas.width = Math.round(viewport.width);
  canvas.height = Math.round(viewport.height);
  return page.render({ canvas, viewport });
}
