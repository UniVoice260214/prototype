import { ApiProperty } from '@nestjs/swagger';
import { IsEmail, IsEnum, IsString, MaxLength, MinLength } from 'class-validator';

export class CreateUserDto {
  @ApiProperty({ example: 'admin@univ.ac.kr' })
  @IsEmail()
  email: string;

  @ApiProperty({ example: 'P@ssw0rd!', minLength: 8 })
  @IsString()
  @MinLength(8)
  password: string;

  @ApiProperty({ example: 'Admin User' })
  @IsString()
  @MaxLength(100)
  name: string;

  @ApiProperty({ enum: ['admin', 'professor'] })
  @IsEnum(['admin', 'professor'])
  role: 'admin' | 'professor';
}
