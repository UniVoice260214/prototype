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
import { CourseService } from './course.service';
import { CreateCourseDto, UpdateCourseDto } from './dto/course.dto';

@ApiBearerAuth()
@ApiTags('courses')
@Controller('courses')
export class CourseController {
  constructor(private readonly service: CourseService) {}

  @Roles('admin', 'professor')
  @Post()
  @ApiOperation({ summary: '과목 생성' })
  create(@Body() dto: CreateCourseDto) {
    return this.service.create(dto);
  }

  @Get()
  @ApiOperation({ summary: '과목 목록 조회 (학과·교수로 필터링 가능)' })
  @ApiQuery({ name: 'departmentId', required: false, description: '학과 UUID 필터' })
  @ApiQuery({ name: 'professorId', required: false, description: '교수 UUID 필터' })
  findAll(
    @Query('departmentId') departmentId?: string,
    @Query('professorId') professorId?: string,
  ) {
    return this.service.findAll({ departmentId, professorId });
  }

  @Get(':courseId')
  @ApiOperation({ summary: '과목 1건 조회' })
  @ApiParam({ name: 'courseId', description: '과목(Course) UUID', format: 'uuid' })
  findOne(@Param('courseId', ParseUUIDPipe) id: string) {
    return this.service.findOne(id);
  }

  @Roles('admin', 'professor')
  @Patch(':courseId')
  @ApiOperation({ summary: '과목 정보 수정' })
  @ApiParam({ name: 'courseId', description: '과목(Course) UUID', format: 'uuid' })
  update(
    @Param('courseId', ParseUUIDPipe) id: string,
    @Body() dto: UpdateCourseDto,
  ) {
    return this.service.update(id, dto);
  }

  @Roles('admin')
  @HttpCode(204)
  @Delete(':courseId')
  @ApiOperation({ summary: '과목 삭제 (admin)' })
  @ApiParam({ name: 'courseId', description: '과목(Course) UUID', format: 'uuid' })
  remove(@Param('courseId', ParseUUIDPipe) id: string) {
    return this.service.remove(id);
  }
}
