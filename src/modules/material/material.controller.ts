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
const MAX_BYTES = 50 * 1024 * 1024;

@ApiBearerAuth()
@ApiTags('materials')
@Controller('materials')
export class MaterialController {
  constructor(private readonly service: MaterialService) {}

  @Roles('admin', 'professor')
  @Post('upload')
  @ApiOperation({ summary: 'Upload lecture materials for indexing' })
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

  @Roles('admin', 'professor')
  @Get()
  @ApiOperation({ summary: 'List materials visible to the current user' })
  @ApiQuery({
    name: 'courseId',
    required: false,
    description: 'Optional course UUID filter',
  })
  @ApiQuery({
    name: 'sessionId',
    required: false,
    description: 'Optional session UUID filter',
  })
  findAll(
    @Query('courseId') courseId: string | undefined,
    @Query('sessionId') sessionId: string | undefined,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.findAll({ courseId, sessionId }, user);
  }

  @Roles('admin', 'professor')
  @Get(':materialId')
  @ApiOperation({ summary: 'Get a material visible to the current user' })
  @ApiParam({
    name: 'materialId',
    description: 'Material UUID',
    format: 'uuid',
  })
  findOne(
    @Param('materialId', ParseUUIDPipe) id: string,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.findOne(id, user);
  }

  @Roles('admin', 'professor')
  @HttpCode(204)
  @Delete(':materialId')
  @ApiOperation({ summary: 'Delete a material and its blob' })
  @ApiParam({
    name: 'materialId',
    description: 'Material UUID',
    format: 'uuid',
  })
  remove(
    @Param('materialId', ParseUUIDPipe) id: string,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.remove(id, user);
  }
}
