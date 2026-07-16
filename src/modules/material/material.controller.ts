import {
  BadRequestException,
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  Param,
  ParseUUIDPipe,
  Post,
  Query,
  UploadedFile,
  UseInterceptors,
} from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import {
  ApiBearerAuth,
  ApiBody,
  ApiConsumes,
  ApiOperation,
  ApiParam,
  ApiQuery,
  ApiTags,
} from '@nestjs/swagger';
import {
  AuthUser,
  CurrentUser,
} from '../../common/decorators/current-user.decorator';
import { Roles } from '../../common/decorators/roles.decorator';
import { MaterialService } from './material.service';
import { UploadMaterialDto } from './dto/material.dto';

const ALLOWED_MIME = [
  'application/pdf',
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
];
const MAX_BYTES = 50 * 1024 * 1024; // 50 MB

@ApiBearerAuth()
@ApiTags('materials')
@Controller('materials')
export class MaterialController {
  constructor(private readonly service: MaterialService) {}

  @Roles('admin', 'professor')
  @Post('upload')
  @ApiOperation({
    summary: 'PDF/PPT 강의자료 업로드 (Blob 저장 + 인덱싱 이벤트 발행)',
  })
  @ApiConsumes('multipart/form-data')
  @ApiBody({
    schema: {
      type: 'object',
      properties: {
        file: { type: 'string', format: 'binary' },
        courseId: { type: 'string', format: 'uuid' },
        sessionId: { type: 'string', format: 'uuid', nullable: true },
        sourceType: { type: 'string', enum: ['lecture', 'major'] },
        week: { type: 'integer', nullable: true },
      },
      required: ['file', 'courseId', 'sourceType'],
    },
  })
  @UseInterceptors(FileInterceptor('file', { limits: { fileSize: MAX_BYTES } }))
  upload(
    @UploadedFile() file: Express.Multer.File,
    @Body() dto: UploadMaterialDto,
    @CurrentUser() user: AuthUser,
  ) {
    if (!file) throw new BadRequestException('file is required');
    if (!ALLOWED_MIME.includes(file.mimetype)) {
      throw new BadRequestException(
        `Unsupported mimetype: ${file.mimetype}. Allowed: ${ALLOWED_MIME.join(', ')}`,
      );
    }
    return this.service.upload(file, dto, user);
  }

  @Get()
  @ApiOperation({ summary: '강의자료 목록 조회 (과목·세션으로 필터링 가능)' })
  @ApiQuery({
    name: 'courseId',
    required: false,
    description: '과목 UUID 필터',
  })
  @ApiQuery({
    name: 'sessionId',
    required: false,
    description: '세션 UUID 필터',
  })
  findAll(
    @Query('courseId') courseId?: string,
    @Query('sessionId') sessionId?: string,
  ) {
    return this.service.findAll({ courseId, sessionId });
  }

  @Get(':materialId')
  @ApiOperation({ summary: '강의자료 1건 조회 (blobUrl·indexingStatus 포함)' })
  @ApiParam({
    name: 'materialId',
    description: '강의자료(Material) UUID',
    format: 'uuid',
  })
  findOne(@Param('materialId', ParseUUIDPipe) id: string) {
    return this.service.findOne(id);
  }

  @Roles('admin', 'professor')
  @HttpCode(204)
  @Delete(':materialId')
  @ApiOperation({ summary: '강의자료 삭제 (DB 레코드 + Blob 원본 함께 정리)' })
  @ApiParam({
    name: 'materialId',
    description: '강의자료(Material) UUID',
    format: 'uuid',
  })
  remove(
    @Param('materialId', ParseUUIDPipe) id: string,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.remove(id, user);
  }
}
