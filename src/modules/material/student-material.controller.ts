import {
  Body,
  Controller,
  HttpCode,
  Param,
  ParseUUIDPipe,
  Post,
  Res,
  StreamableFile,
} from '@nestjs/common';
import {
  ApiOkResponse,
  ApiOperation,
  ApiParam,
  ApiProduces,
  ApiTags,
} from '@nestjs/swagger';
import type { Response } from 'express';
import type { Readable } from 'node:stream';
import {
  AuthUser,
  CurrentUser,
} from '../../common/decorators/current-user.decorator';
import { Public } from '../../common/decorators/public.decorator';
import { MaterialService } from './material.service';
import {
  StudentMaterialDto,
  StudentMaterialQueryDto,
} from './dto/material.dto';

/**
 * RFC 5987 ext-value. encodeURIComponent 는 ' ( ) ! * 를 남기는데 ' 는 문법을
 * 깨뜨리므로 마저 인코딩하고, 구형 클라이언트용 ASCII fallback 도 붙인다.
 */
function contentDisposition(filename: string): string {
  const encoded = encodeURIComponent(filename).replace(
    /['()!*]/g,
    (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`,
  );
  const ascii = filename.replace(/[^\x20-\x7e]/g, '_').replace(/["\\]/g, '_');
  return `inline; filename="${ascii}"; filename*=UTF-8''${encoded}`;
}

/**
 * 학생용 자료 조회. joinToken 이 URL 에 남지 않도록 GET 대신 POST body 로 받는다
 * (transcripts/query 와 같은 규칙). 파일은 서버가 Blob 을 프록시해 내려준다.
 */
@ApiTags('materials')
@Controller('sessions/:sessionId/materials')
export class StudentMaterialController {
  constructor(private readonly service: MaterialService) {}

  @Public()
  @HttpCode(200)
  @Post('query')
  @ApiOperation({
    summary: 'List course materials for a session (Student JWT or join token)',
  })
  @ApiParam({ name: 'sessionId', description: 'Session UUID', format: 'uuid' })
  @ApiOkResponse({ type: StudentMaterialDto, isArray: true })
  listForStudent(
    @Param('sessionId', ParseUUIDPipe) sessionId: string,
    @Body() dto: StudentMaterialQueryDto,
    @CurrentUser() user: AuthUser | undefined,
  ): Promise<StudentMaterialDto[]> {
    const studentId = user?.type === 'student' ? user.sub : null;
    return this.service.listForStudent(sessionId, dto, studentId);
  }

  @Public()
  @HttpCode(200)
  @Post(':materialId/file')
  @ApiOperation({
    summary: 'Stream the PDF preview of a material (Student JWT or join token)',
  })
  @ApiParam({ name: 'sessionId', description: 'Session UUID', format: 'uuid' })
  @ApiParam({
    name: 'materialId',
    description: 'Material UUID',
    format: 'uuid',
  })
  @ApiProduces('application/pdf')
  async file(
    @Param('sessionId', ParseUUIDPipe) sessionId: string,
    @Param('materialId', ParseUUIDPipe) materialId: string,
    @Body() dto: StudentMaterialQueryDto,
    @CurrentUser() user: AuthUser | undefined,
    @Res({ passthrough: true }) res: Response,
  ): Promise<StreamableFile> {
    const studentId = user?.type === 'student' ? user.sub : null;
    const file = await this.service.streamForStudent(
      sessionId,
      materialId,
      dto,
      studentId,
    );
    res.setHeader('Content-Type', file.contentType);
    res.setHeader('Content-Disposition', contentDisposition(file.filename));
    res.setHeader('Cache-Control', 'private, no-store');
    if (file.contentLength) res.setHeader('Content-Length', file.contentLength);
    return new StreamableFile(file.stream as Readable);
  }
}
