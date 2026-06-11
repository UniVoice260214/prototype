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
import { DepartmentService } from './department.service';
import {
  CreateDepartmentDto,
  UpdateDepartmentDto,
} from './dto/department.dto';

@ApiBearerAuth()
@ApiTags('departments')
@Controller('departments')
export class DepartmentController {
  constructor(private readonly service: DepartmentService) {}

  @Roles('admin')
  @Post()
  @ApiOperation({ summary: '학과 생성' })
  create(@Body() dto: CreateDepartmentDto) {
    return this.service.create(dto);
  }

  @Get()
  @ApiOperation({ summary: '학과 목록 조회 (schoolId로 필터링 가능)' })
  @ApiQuery({ name: 'schoolId', required: false, description: '학교 UUID 필터' })
  findAll(@Query('schoolId') schoolId?: string) {
    return this.service.findAll(schoolId);
  }

  @Get(':departmentId')
  @ApiOperation({ summary: '학과 1건 조회' })
  @ApiParam({ name: 'departmentId', description: '학과(Department) UUID', format: 'uuid' })
  findOne(@Param('departmentId', ParseUUIDPipe) id: string) {
    return this.service.findOne(id);
  }

  @Roles('admin')
  @Patch(':departmentId')
  @ApiOperation({ summary: '학과 정보 수정' })
  @ApiParam({ name: 'departmentId', description: '학과(Department) UUID', format: 'uuid' })
  update(
    @Param('departmentId', ParseUUIDPipe) id: string,
    @Body() dto: UpdateDepartmentDto,
  ) {
    return this.service.update(id, dto);
  }

  @Roles('admin')
  @HttpCode(204)
  @Delete(':departmentId')
  @ApiOperation({ summary: '학과 삭제' })
  @ApiParam({ name: 'departmentId', description: '학과(Department) UUID', format: 'uuid' })
  remove(@Param('departmentId', ParseUUIDPipe) id: string) {
    return this.service.remove(id);
  }
}
