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
import { Roles } from '../../common/decorators/roles.decorator';
import { ProfessorService } from './professor.service';
import {
  CreateProfessorDto,
  UpdateProfessorDto,
} from './dto/professor.dto';

@ApiBearerAuth()
@ApiTags('professors')
@Controller('professors')
export class ProfessorController {
  constructor(private readonly service: ProfessorService) {}

  @Roles('admin')
  @Post()
  @ApiOperation({
    summary: '교수 프로필 생성 (role=professor 인 User와 1:1 연결, 학과 소속)',
  })
  create(@Body() dto: CreateProfessorDto) {
    return this.service.create(dto);
  }

  @Get()
  @ApiOperation({ summary: '교수 목록 조회 (departmentId로 필터링 가능)' })
  @ApiQuery({ name: 'departmentId', required: false, description: '학과 UUID 필터' })
  findAll(@Query('departmentId') departmentId?: string) {
    return this.service.findAll(departmentId);
  }

  @Get(':professorId')
  @ApiOperation({ summary: '교수 1건 조회 (연결된 User 정보 포함)' })
  @ApiParam({ name: 'professorId', description: '교수(Professor) UUID', format: 'uuid' })
  findOne(@Param('professorId', ParseUUIDPipe) id: string) {
    return this.service.findOne(id);
  }

  @Roles('admin')
  @Patch(':professorId')
  @ApiOperation({ summary: '교수 정보 수정 (학과 변경 등)' })
  @ApiParam({ name: 'professorId', description: '교수(Professor) UUID', format: 'uuid' })
  update(
    @Param('professorId', ParseUUIDPipe) id: string,
    @Body() dto: UpdateProfessorDto,
  ) {
    return this.service.update(id, dto);
  }

  @Roles('admin')
  @HttpCode(204)
  @Delete(':professorId')
  @ApiOperation({ summary: '교수 프로필 삭제 (User는 유지됨)' })
  @ApiParam({ name: 'professorId', description: '교수(Professor) UUID', format: 'uuid' })
  remove(@Param('professorId', ParseUUIDPipe) id: string) {
    return this.service.remove(id);
  }
}
