import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import {
  ArrayMinSize,
  IsArray,
  IsIn,
  IsOptional,
  IsString,
  IsUUID,
} from 'class-validator';
import { SUPPORTED_TARGET_LOCALES } from '../../../common/supported-locales';

export class StartSessionDto {
  @ApiProperty({ format: 'uuid' })
  @IsUUID()
  courseId: string;

  @ApiProperty({
    example: ['zh-CN', 'vi-VN', 'mn-MN'],
    description: 'List of locales to translate and publish for this session',
  })
  @IsArray()
  @ArrayMinSize(1)
  @IsString({ each: true })
  @IsIn(SUPPORTED_TARGET_LOCALES, { each: true })
  targetLocales: string[];
}

export class IssueStudentTokenDto {
  @ApiPropertyOptional({
    description:
      'Join token issued from the QR flow. Optional when a Student JWT is used.',
  })
  @IsOptional()
  @IsString()
  joinToken?: string;

  @ApiProperty({ example: 'vi-VN' })
  @IsString()
  @IsIn(SUPPORTED_TARGET_LOCALES)
  locale: string;
}

export class LiveKitTokenResponseDto {
  @ApiProperty()
  liveKitUrl: string;

  @ApiProperty()
  token: string;

  @ApiProperty()
  roomName: string;

  @ApiProperty()
  identity: string;
}
