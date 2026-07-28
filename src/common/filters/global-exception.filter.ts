import {
  ArgumentsHost,
  Catch,
  ExceptionFilter,
  HttpException,
  HttpStatus,
  Logger,
} from '@nestjs/common';
import { Request, Response } from 'express';

interface ErrorPayload {
  statusCode: number;
  error: string;
  message: string | string[];
  path: string;
  timestamp: string;
}

@Catch()
export class GlobalExceptionFilter implements ExceptionFilter {
  private readonly logger = new Logger(GlobalExceptionFilter.name);

  catch(exception: unknown, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const request = ctx.getRequest<Request>();
    const response = ctx.getResponse<Response>();

    let status = HttpStatus.INTERNAL_SERVER_ERROR;
    let errorCode = 'INTERNAL_SERVER_ERROR';
    let message: string | string[] = 'Internal server error';

    if (exception instanceof HttpException) {
      status = exception.getStatus();
      const res = exception.getResponse();
      if (status >= 500) {
        message = 'Internal server error';
        errorCode = HttpStatus[status] ?? 'HTTP_ERROR';
        this.logger.error(exception.stack ?? exception.message);
      } else if (typeof res === 'string') {
        message = res;
        errorCode = HttpStatus[status] ?? 'HTTP_ERROR';
      } else if (typeof res === 'object' && res !== null) {
        const obj = res as { message?: string | string[]; error?: string };
        message = obj.message ?? exception.message;
        errorCode = obj.error ?? HttpStatus[status] ?? 'HTTP_ERROR';
      }
    } else if (exception instanceof Error) {
      this.logger.error(exception.stack);
    } else {
      this.logger.error(`Non-error exception: ${String(exception)}`);
    }

    const payload: ErrorPayload = {
      statusCode: status,
      error: errorCode,
      message,
      path: request.url,
      timestamp: new Date().toISOString(),
    };

    response.status(status).json(payload);
  }
}
