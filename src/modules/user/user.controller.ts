import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  Param,
  ParseUUIDPipe,
  Post,
} from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiParam, ApiTags } from '@nestjs/swagger';
import { Roles } from '../../common/decorators/roles.decorator';
import { UserService } from './user.service';
import { CreateUserDto } from './dto/create-user.dto';

@ApiBearerAuth()
@ApiTags('users')
@Roles('admin')
@Controller('users')
export class UserController {
  constructor(private readonly users: UserService) {}

  @Post()
  @ApiOperation({ summary: 'User 생성 (admin/professor)' })
  create(@Body() dto: CreateUserDto) {
    return this.users.create(dto);
  }

  @Get()
  @ApiOperation({ summary: 'User 목록 조회 (admin/professor 전체)' })
  findAll() {
    return this.users.findAll();
  }

  @Get(':userId')
  @ApiOperation({ summary: 'User 1건 조회' })
  @ApiParam({ name: 'userId', description: 'User(admin/professor) UUID', format: 'uuid' })
  findOne(@Param('userId', ParseUUIDPipe) id: string) {
    return this.users.findOne(id);
  }

  @HttpCode(204)
  @Delete(':userId')
  @ApiOperation({ summary: 'User 삭제 (연결된 Professor 프로필도 함께 삭제)' })
  @ApiParam({ name: 'userId', description: 'User(admin/professor) UUID', format: 'uuid' })
  remove(@Param('userId', ParseUUIDPipe) id: string) {
    return this.users.remove(id);
  }
}
