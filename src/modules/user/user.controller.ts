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
import {
  ApiBearerAuth,
  ApiOperation,
  ApiParam,
  ApiTags,
} from '@nestjs/swagger';
import { Roles } from '../../common/decorators/roles.decorator';
import { CreateUserDto } from './dto/create-user.dto';
import { UserService } from './user.service';

@ApiBearerAuth()
@ApiTags('users')
@Roles('admin')
@Controller('users')
export class UserController {
  constructor(private readonly users: UserService) {}

  @Post()
  @ApiOperation({ summary: 'Create an admin or professor user' })
  create(@Body() dto: CreateUserDto) {
    return this.users.create(dto);
  }

  @Get()
  @ApiOperation({ summary: 'List admin and professor users' })
  findAll() {
    return this.users.findAll();
  }

  @Get(':userId')
  @ApiOperation({ summary: 'Get a single user' })
  @ApiParam({
    name: 'userId',
    description: 'User UUID',
    format: 'uuid',
  })
  findOne(@Param('userId', ParseUUIDPipe) id: string) {
    return this.users.findOne(id);
  }

  @HttpCode(204)
  @Delete(':userId')
  @ApiOperation({ summary: 'Delete a user and any linked professor profile' })
  @ApiParam({
    name: 'userId',
    description: 'User UUID',
    format: 'uuid',
  })
  remove(@Param('userId', ParseUUIDPipe) id: string) {
    return this.users.remove(id);
  }
}
