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
import { CreateDepartmentDto, UpdateDepartmentDto } from './dto/department.dto';

@ApiBearerAuth()
@ApiTags('departments')
@Controller('departments')
export class DepartmentController {
  constructor(private readonly service: DepartmentService) {}

  @Roles('admin')
  @Post()
  @ApiOperation({ summary: 'Create a department' })
  create(@Body() dto: CreateDepartmentDto) {
    return this.service.create(dto);
  }

  @Roles('admin', 'professor')
  @Get()
  @ApiOperation({ summary: 'List departments' })
  @ApiQuery({
    name: 'schoolId',
    required: false,
    description: 'Optional school UUID filter',
  })
  findAll(@Query('schoolId') schoolId?: string) {
    return this.service.findAll(schoolId);
  }

  @Roles('admin', 'professor')
  @Get(':departmentId')
  @ApiOperation({ summary: 'Get a single department' })
  @ApiParam({
    name: 'departmentId',
    description: 'Department UUID',
    format: 'uuid',
  })
  findOne(@Param('departmentId', ParseUUIDPipe) id: string) {
    return this.service.findOne(id);
  }

  @Roles('admin')
  @Patch(':departmentId')
  @ApiOperation({ summary: 'Update a department' })
  @ApiParam({
    name: 'departmentId',
    description: 'Department UUID',
    format: 'uuid',
  })
  update(
    @Param('departmentId', ParseUUIDPipe) id: string,
    @Body() dto: UpdateDepartmentDto,
  ) {
    return this.service.update(id, dto);
  }

  @Roles('admin')
  @HttpCode(204)
  @Delete(':departmentId')
  @ApiOperation({ summary: 'Delete a department' })
  @ApiParam({
    name: 'departmentId',
    description: 'Department UUID',
    format: 'uuid',
  })
  remove(@Param('departmentId', ParseUUIDPipe) id: string) {
    return this.service.remove(id);
  }
}
