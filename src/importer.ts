import { createWorker, type Worker } from 'tesseract.js';
import workerPath from 'tesseract.js/dist/worker.min.js?url';
import { call, errorText, readMedia } from './api';
import type { ImportResult, Unit } from './types';
import { openPdf, renderPage } from './pdf';

export const importExtensions = [
  'pdf', 'docx', 'pptx', 'xlsx', 'xls', 'xlsb', 'ods', 'odt', 'odp', 'epub',
  'txt', 'md', 'markdown', 'html', 'htm', 'csv', 'tsv', 'json', 'jsonl', 'yaml', 'yml', 'xml', 'log', 'srt', 'vtt',
  'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff',
];

export async function completeImport(result: ImportResult, token: string, languages: string, progress: (message: string) => void) {
  if (result.duplicate || !result.needsExtraction) return;
  const { source } = result;
  const sourceId = source.id;
  let worker: Worker | undefined;
  const recognize = async (input: File | HTMLCanvasElement) => {
    if (!worker) {
      progress(`${source.name} · 正在载入 OCR 语言模型`);
      worker = await createWorker(languages.split('+'), 1, { workerPath, workerBlobURL: false });
    }
    const { data } = await worker.recognize(input);
    return { text: data.text.trim(), confidence: Math.min(1, Math.max(0, data.confidence / 100)) };
  };
  try {
    if (source.extension === 'pdf') {
      const { pdf, close } = await openPdf(sourceId, source.bytes, token);
      const canvas = document.createElement('canvas');
      try {
        let pending: Unit[] = [];
        for (let ordinal = 1; ordinal <= pdf.numPages; ordinal++) {
          progress(`${source.name} · 第 ${ordinal} / ${pdf.numPages} 页`);
          const page = await pdf.getPage(ordinal);
          const content = await page.getTextContent();
          const text = content.items.map(item => 'str' in item ? item.str + (item.hasEOL ? '\n' : ' ') : '').join('').trim();
          const visibleCharacters = text.match(/[\p{L}\p{N}]/gu)?.length ?? 0;
          const characters = text.match(/\S/gu)?.length ?? 0;
          const locator = `PDF 第 ${ordinal} 页`;
          if (visibleCharacters >= 25 && visibleCharacters / characters > 0.55) {
            pending.push({ ordinal, kind: 'page', locator, text, method: 'native' });
          } else {
            await (await renderPage(pdf, ordinal, 1550, canvas)).promise;
            const ocr = await recognize(canvas);
            pending.push({ ordinal, kind: 'page', locator, method: 'ocr', ...ocr });
          }
          page.cleanup();
          if (pending.length === 8 || ordinal === pdf.numPages) {
            await call('submit_units', { token, sourceId, units: pending });
            pending = [];
          }
        }
      } finally {
        canvas.width = 0;
        await close();
      }
    } else {
      const blob = await readMedia(sourceId, source.bytes, token);
      const ocr = await recognize(new File([blob], source.name));
      await call('submit_units', { token, sourceId, units: [{ ordinal: 1, kind: 'image', locator: '原始图像', method: 'ocr', ...ocr }] });
    }
    await call('finish_import', { token, sourceId });
  } catch (error) {
    await call('fail_import', { token, sourceId, error: errorText(error) });
    throw error;
  } finally {
    if (worker) await worker.terminate();
  }
}
