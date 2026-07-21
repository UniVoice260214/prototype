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
import { CourseService } from './course.service';
import { CreateCourseDto, UpdateCourseDto } from './dto/course.dto';

@ApiBearerAuth()
@ApiTags('courses')
@Controller('courses')
export class CourseController {
  constructor(private readonly service: CourseService) {}

  @Roles('admin', 'professor')
  @Post()
  @ApiOperation({ summary: 'Create a course' })
  create(@Body() dto: CreateCourseDto) {
    return this.service.create(dto);
  }

  @Roles('admin', 'professor')
  @Get()
  @ApiOperation({ summary: 'List courses visible to the current user' })
  @ApiQuery({
    name: 'departmentId',
    required: false,
    description: 'Optional department UUID filter',
  })
  @ApiQuery({
    name: 'professorId',
    required: false,
    description: 'Optional professor UUID filter',
  })
  findAll(
    @CurrentUser() user: AuthUser,
    @Query('departmentId') departmentId?: string,
    @Query('professorId') professorId?: string,
  ) {
    return this.service.findAll({ departmentId, professorId }, user);
  }

  @Roles('admin', 'professor')
  @Get(':courseId')
  @ApiOperation({ summary: 'Get a single course visible to the current user' })
  @ApiParam({
    name: 'courseId',
    description: 'Course UUID',
    format: 'uuid',
  })
  findOne(
    @Param('courseId', ParseUUIDPipe) id: string,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.findOne(id, user);
  }

  @Roles('admin', 'professor')
  @Patch(':courseId')
  @ApiOperation({ summary: 'Update a course' })
  @ApiParam({
    name: 'courseId',
    description: 'Course UUID',
    format: 'uuid',
  })
  update(
    @Param('courseId', ParseUUIDPipe) id: string,
    @Body() dto: UpdateCourseDto,
  ) {
    return this.service.update(id, dto);
  }

  @Roles('admin')
  @HttpCode(204)
  @Delete(':courseId')
  @ApiOperation({ summary: 'Delete a course' })
  @ApiParam({
    name: 'courseId',
    description: 'Course UUID',
    format: 'uuid',
  })
  remove(@Param('courseId', ParseUUIDPipe) id: string) {
    return this.service.remove(id);
  }
}
