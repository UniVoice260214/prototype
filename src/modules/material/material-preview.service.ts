import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { spawn } from 'node:child_process';
import { promises as fs } from 'node:fs';
import { tmpdir } from 'node:os';
import { extname, join } from 'node:path';

type ConverterMode = 'auto' | 'powerpoint' | 'soffice' | 'off';

interface Converter {
  name: string;
  run: (input: string, output: string) => Promise<void>;
}

interface PreviewSource {
  buffer: Buffer;
  originalname: string;
  mimetype: string;
}

/**
 * 브라우저는 PPT/PPTX 를 그리지 못하므로 학생 화면용 PDF 로 변환한다.
 * Windows 는 PowerPoint COM, 그 외는 LibreOffice(soffice) 를 쓴다.
 * 어느 쪽도 없거나 실패하면 null — 자료는 남고 미리보기만 failed 가 된다.
 */
@Injectable()
export class MaterialPreviewService {
  private readonly logger = new Logger(MaterialPreviewService.name);
  private readonly mode: ConverterMode;
  private readonly timeoutMs: number;
  // PowerPoint COM 은 단일 인스턴스라 동시 Open 이 RPC_E_CALL_REJECTED 로 실패한다.
  // 변환은 한 번에 하나만 돌린다.
  private queue: Promise<unknown> = Promise.resolve();

  constructor(config: ConfigService) {
    this.mode = config.get<ConverterMode>('MATERIAL_PREVIEW_CONVERTER', 'auto');
    this.timeoutMs = Number(
      config.get<string>('MATERIAL_PREVIEW_TIMEOUT_MS', '120000'),
    );
  }

  /** 브라우저가 보낸 mimetype 은 믿지 않는다 — 실제 바이트(%PDF-)로 판정. */
  isPdf(file: { buffer: Buffer }): boolean {
    return file.buffer.subarray(0, 5).toString('latin1') === '%PDF-';
  }

  convertToPdf(file: PreviewSource): Promise<Buffer | null> {
    if (this.mode === 'off') return Promise.resolve(null);
    const converters = this.converters();
    if (!converters.length) {
      this.logger.warn('No PPT->PDF converter available on this platform');
      return Promise.resolve(null);
    }
    const run = this.queue.then(() => this.convertNow(file, converters));
    this.queue = run.catch(() => undefined);
    return run;
  }

  private async convertNow(
    file: PreviewSource,
    converters: Converter[],
  ): Promise<Buffer | null> {
    const workDir = await fs.mkdtemp(join(tmpdir(), 'univoice-preview-'));
    const ext = extname(file.originalname).toLowerCase() || '.pptx';
    const input = join(workDir, `source${ext}`);
    const output = join(workDir, 'source.pdf');
    try {
      await fs.writeFile(input, file.buffer);
      for (const converter of converters) {
        try {
          await converter.run(input, output);
          const pdf = await fs.readFile(output);
          if (pdf.length > 0) return pdf;
          this.logger.warn(`${converter.name} produced an empty PDF`);
        } catch (err) {
          this.logger.warn(
            `${converter.name} conversion failed for ${file.originalname}: ${this.errorMessage(err)}`,
          );
        }
      }
      return null;
    } finally {
      await this.removeWorkDir(workDir);
    }
  }

  /** 타임아웃으로 죽인 프로세스가 파일을 잠깐 더 잡고 있을 수 있어 한 번 더 시도한다. */
  private async removeWorkDir(workDir: string): Promise<void> {
    for (const delay of [0, 2000]) {
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
      try {
        await fs.rm(workDir, { recursive: true, force: true });
        return;
      } catch {
        // retry
      }
    }
    this.logger.warn(`Temp dir not removed: ${workDir}`);
  }

  private converters(): Converter[] {
    const list: Converter[] = [];
    if (
      (this.mode === 'auto' || this.mode === 'powerpoint') &&
      process.platform === 'win32'
    ) {
      list.push({
        name: 'powerpoint',
        run: (i, o) => this.runPowerPoint(i, o),
      });
    }
    if (this.mode === 'auto' || this.mode === 'soffice') {
      list.push({ name: 'soffice', run: (i, o) => this.runSoffice(i, o) });
    }
    return list;
  }

  /**
   * PowerPoint COM 자동화. 사용자가 이미 PowerPoint 를 열어 두었다면 같은
   * 인스턴스에 붙으므로, 우리가 새로 띄운 경우에만 Quit 한다.
   * Open(FileName, ReadOnly=msoTrue, Untitled=msoFalse, WithWindow=msoFalse),
   * SaveAs(FileName, ppSaveAsPDF=32)
   */
  private runPowerPoint(input: string, output: string): Promise<void> {
    const q = (value: string) => `'${value.replace(/'/g, "''")}'`;
    // Open 이 실패해도(손상 파일, 보호된 보기) finally 가 돌아 Quit 되도록
    // 생성부터 통째로 try 안에 둔다.
    const script = [
      "$ErrorActionPreference = 'Stop'",
      '$app = $null; $pres = $null; $owned = $false',
      'try {',
      '  $app = New-Object -ComObject PowerPoint.Application',
      '  $owned = $app.Presentations.Count -eq 0',
      `  $pres = $app.Presentations.Open(${q(input)}, -1, 0, 0)`,
      `  $pres.SaveAs(${q(output)}, 32)`,
      '} finally {',
      '  if ($pres) { $pres.Close() }',
      '  if ($app -and $owned) { $app.Quit() }',
      '}',
    ].join('\n');
    return this.exec('powershell.exe', [
      '-NoProfile',
      '-NonInteractive',
      '-ExecutionPolicy',
      'Bypass',
      '-Command',
      script,
    ]);
  }

  private runSoffice(input: string, output: string): Promise<void> {
    const outDir = join(output, '..');
    return this.exec('soffice', [
      '--headless',
      '--convert-to',
      'pdf',
      '--outdir',
      outDir,
      input,
    ]);
  }

  private exec(command: string, args: string[]): Promise<void> {
    return new Promise((resolve, reject) => {
      const child = spawn(command, args, {
        windowsHide: true,
        stdio: ['ignore', 'ignore', 'pipe'],
      });
      let stderr = '';
      child.stderr?.on('data', (chunk: Buffer) => {
        stderr += chunk.toString();
      });
      const timer = setTimeout(() => {
        this.killTree(child.pid);
        reject(new Error(`${command} timed out after ${this.timeoutMs}ms`));
      }, this.timeoutMs);
      child.on('error', (err) => {
        clearTimeout(timer);
        reject(err);
      });
      child.on('close', (code) => {
        clearTimeout(timer);
        if (code === 0) resolve();
        else
          reject(
            new Error(
              `${command} exited ${code}: ${stderr.trim().slice(0, 400)}`,
            ),
          );
      });
    });
  }

  /** COM 으로 띄운 PowerPoint 는 자식이 아니라서 kill() 로는 안 죽는다. */
  private killTree(pid: number | undefined): void {
    if (!pid) return;
    if (process.platform === 'win32') {
      spawn('taskkill', ['/T', '/F', '/PID', String(pid)], {
        windowsHide: true,
        stdio: 'ignore',
      }).on('error', () => undefined);
    } else {
      try {
        process.kill(pid, 'SIGKILL');
      } catch {
        // already gone
      }
    }
  }

  private errorMessage(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }
}
