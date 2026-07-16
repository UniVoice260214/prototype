import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  Param,
  ParseUUIDPipe,
  Patch,
  Post,
  Query,
} from '@nestjs/common';
import {
  ApiBearerAuth,
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
import { GlossaryService } from './glossary.service';
import { CreateGlossaryDto, UpdateGlossaryDto } from './dto/glossary.dto';

@ApiBearerAuth()
@ApiTags('glossary')
@Controller('glossary')
export class GlossaryController {
  constructor(private readonly service: GlossaryService) {}

  @Roles('admin', 'professor')
  @Post()
  @ApiOperation({
    summary: '용어 등록 (다국어 번역·발음 포함, Redis 캐시 무효화)',
  })
  create(@Body() dto: CreateGlossaryDto, @CurrentUser() user: AuthUser) {
    return this.service.create(dto, user);
  }

  @Get()
  @ApiOperation({ summary: '용어 목록 조회 (courseId로 필터링 가능)' })
  @ApiQuery({
    name: 'courseId',
    required: false,
    description: '과목 UUID 필터',
  })
  findAll(@Query('courseId') courseId?: string) {
    return this.service.findAll(courseId);
  }

  @Get(':glossaryId')
  @ApiOperation({ summary: '용어 1건 조회' })
  @ApiParam({
    name: 'glossaryId',
    description: '용어(Glossary) UUID',
    format: 'uuid',
  })
  findOne(@Param('glossaryId', ParseUUIDPipe) id: string) {
    return this.service.findOne(id);
  }

  @Roles('admin', 'professor')
  @Patch(':glossaryId')
  @ApiOperation({
    summary: '용어 정보 수정 (번역·발음·정의, Redis 캐시 무효화)',
  })
  @ApiParam({
    name: 'glossaryId',
    description: '용어(Glossary) UUID',
    format: 'uuid',
  })
  update(
    @Param('glossaryId', ParseUUIDPipe) id: string,
    @Body() dto: UpdateGlossaryDto,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.update(id, dto, user);
  }

  @Roles('admin', 'professor')
  @HttpCode(204)
  @Delete(':glossaryId')
  @ApiOperation({ summary: '용어 삭제 (Redis 캐시 무효화)' })
  @ApiParam({
    name: 'glossaryId',
    description: '용어(Glossary) UUID',
    format: 'uuid',
  })
  remove(
    @Param('glossaryId', ParseUUIDPipe) id: string,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.remove(id, user);
  }
}
