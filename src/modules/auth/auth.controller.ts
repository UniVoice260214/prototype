import { Body, Controller, HttpCode, Post } from '@nestjs/common';
import { ApiOkResponse, ApiOperation, ApiTags } from '@nestjs/swagger';
import { Public } from '../../common/decorators/public.decorator';
import { AuthService } from './auth.service';
import { LoginDto, TokenResponseDto } from './dto/login.dto';
import { SignupStudentDto } from './dto/signup-student.dto';

@ApiTags('auth')
@Controller('auth')
export class AuthController {
  constructor(private readonly auth: AuthService) {}

  @Public()
  @HttpCode(200)
  @Post('login')
  @ApiOperation({ summary: 'Admin/professor login' })
  @ApiOkResponse({ type: TokenResponseDto })
  login(@Body() dto: LoginDto) {
    return this.auth.loginUser(dto);
  }

  @Public()
  @Post('student/signup')
  @ApiOperation({ summary: 'Student signup' })
  @ApiOkResponse({ type: TokenResponseDto })
  signupStudent(@Body() dto: SignupStudentDto) {
    return this.auth.signupStudent(dto);
  }

  @Public()
  @HttpCode(200)
  @Post('student/login')
  @ApiOperation({ summary: 'Student login' })
  @ApiOkResponse({ type: TokenResponseDto })
  loginStudent(@Body() dto: LoginDto) {
    return this.auth.loginStudent(dto);
  }
}
